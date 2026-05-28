"""
智学网自动阅卷 — 图片识别 + 覆盖层定位
"""

import os
import io
import json
import time
import base64
import threading
from datetime import datetime
from openai import OpenAI
from browser_manager import create_driver
from element_finder import ElementFinder

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(SCREENSHOT_DIR, "last_session.json")

# ========== 全局状态 ==========
# 整个自动阅卷流程的状态机，前端通过轮询 /api/auto/status 获取此状态
_state = {
    "status": "idle",           # 主状态：idle→starting→login_waiting→page_waiting→detecting→locating→running→finished
    "message": "等待开始",       # 当前提示信息，显示在前端状态栏
    "progress": 0,              # 已批改份数
    "total": 0,                 # 总批改份数
    "max_score": 100,           # 满分
    "results": [],              # 批改结果列表
    "latest_screenshot": "",    # 最新截图路径
    "stop_requested": False,    # 用户是否请求停止
    "driver": None,             # Selenium WebDriver 实例（不序列化到前端）
    "finder": None,             # ElementFinder 实例（不序列化到前端）
    "login_confirmed": False,   # 用户是否确认已登录
    "page_confirmed": False,    # 用户是否确认页面就绪
    "locate_mode": "auto",      # 定位方式："auto"（自动检测）或 "manual"（手动标记）
    "locate_phase": "",         # 定位子阶段（见下方说明）
    "detected_info": None,      # 自动模式下检测到的元素信息
    "score_pos": None,          # 手动模式：打分框的视口坐标 {x, y}
    "submit_pos": None,         # 手动模式：提交按钮的视口坐标 {x, y}
    "reference": "",            # 参考答案与评分标准
}
# 线程锁：Flask 请求处理和后台批改线程并发访问 _state，需要加锁保护
_state_lock = threading.Lock()

# locate_phase 子阶段说明：
#   "auto_confirm"      - 自动检测完成，等待用户确认
#   "manual_mark_score" - 手动模式，等待用户点击打分框
#   "manual_mark_submit"- 手动模式，打分框已标记，等待用户点击提交按钮
#   "manual_done"       - 手动模式，两处都已标记，等待用户确认
#   "awaiting_confirm"  - 已处理完标记，等待用户点击「确认定位」
#   "confirmed"         - 用户已确认，退出定位阶段
#   "re_detecting"      - 用户请求重新检测/标记


def _get(key):
    with _state_lock:
        return _state[key]

def _set(key, value):
    with _state_lock:
        _state[key] = value


def get_state():
    with _state_lock:
        out = {}
        for k, v in _state.items():
            if k in ("driver", "finder"):
                continue
            if k == "results":
                out[k] = v[-50:]
            else:
                out[k] = v
        return out


def load_last_session():
    """读取上次批改结果摘要"""
    try:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def start_grader(reference, count, browser_type, api_key, api_base, model, max_score=100, locate_mode="auto", target_url="https://www.zhixue.com"):
    old_driver = _get("driver")
    if old_driver:
        try:
            old_driver.quit()
        except Exception:
            pass
        _set("driver", None)
        time.sleep(1)

    _set("stop_requested", False)
    _set("status", "starting")
    _set("message", "正在启动浏览器...")
    _set("progress", 0)
    _set("total", count)
    _set("reference", reference.strip())
    _set("max_score", int(max_score))
    _set("results", [])
    _set("latest_screenshot", "")
    _set("login_confirmed", False)
    _set("page_confirmed", False)
    _set("locate_mode", locate_mode)
    _set("locate_phase", "")
    _set("detected_info", None)
    _set("score_pos", None)
    _set("submit_pos", None)
    _set("finder", None)
    t = threading.Thread(target=_run, args=(reference, count, browser_type, api_key, api_base, model, int(max_score), target_url), daemon=True)
    t.start()


def confirm_login():
    _set("login_confirmed", True)
    status = _get("status")
    if status in ("login_waiting", "auto_login_detected"):
        _set("status", "login_confirmed")
        _set("message", "登录已确认...")


def confirm_ready():
    _set("page_confirmed", True)
    status = _get("status")
    if status in ("page_waiting",):
        _set("status", "page_confirmed")
        _set("message", "页面已确认，正在分析...")


def confirm_locate():
    """
    用户点击「确认定位」按钮后调用。
    关键逻辑：
    1. 手动模式下，直接将坐标写入 finder（避免与主循环的竞态条件）
    2. 移除覆盖层和高亮
    3. 将状态推进到「locate_confirmed」，主循环检测到后开始批改
    """
    status = _get("status")
    phase = _get("locate_phase")
    # 支持多种子阶段：自动确认、手动完成、等待确认、已确认
    if status == "locating" and phase in ("auto_confirm", "manual_done", "awaiting_confirm", "confirmed"):
        # 手动模式：直接设置 finder 坐标，不依赖主循环处理
        # 这样即使主循环还没处理 manual_done，坐标也已经就位
        if _get("locate_mode") == "manual":
            sp = _get("score_pos")
            bp = _get("submit_pos")
            finder = _get("finder")
            if sp and bp and finder:
                finder.set_manual_score(sp["x"], sp["y"])
                finder.set_manual_submit(bp["x"], bp["y"])
        # 移除覆盖层和元素高亮
        remove_overlay(_get("driver"))
        clear_highlights(_get("driver"))
        # 推进状态，主循环会检测到并退出定位阶段
        _set("locate_phase", "confirmed")
        _set("status", "locate_confirmed")
        _set("message", "定位已确认，开始批改...")


def redo_locate():
    status = _get("status")
    if status == "locating":
        remove_overlay(_get("driver"))
        clear_highlights(_get("driver"))
        _set("locate_phase", "re_detecting")
        _set("message", "正在重新检测...")


def update_reference(ref):
    _set("reference", ref.strip())
    print("[auto] 批改标准已更新")


def mark_score_pos(x, y):
    """
    覆盖层回调：用户在浏览器中点击了打分框位置。
    保存坐标，将子阶段从「等待点打分框」推进到「等待点提交按钮」。
    """
    status = _get("status")
    if status == "locating":
        _set("score_pos", {"x": int(x), "y": int(y)})
        phase = _get("locate_phase")
        if phase == "manual_mark_score":
            _set("locate_phase", "manual_mark_submit")
            _set("message", "打分框已标记，请在浏览器中点击提交按钮位置")
        return True
    return False


def mark_submit_pos(x, y):
    """
    覆盖层回调：用户在浏览器中点击了提交按钮位置。
    保存坐标，将子阶段设为「manual_done」（两处都已标记）。
    前端轮询到 manual_done 后会显示「确认定位」按钮。
    """
    status = _get("status")
    if status == "locating":
        _set("submit_pos", {"x": int(x), "y": int(y)})
        _set("locate_phase", "manual_done")
        _set("message", "两处已标记，请在页面中确认定位")
        return True
    return False


def overlay_done():
    """覆盖层「完成标记」被点击，读取坐标"""
    status = _get("status")
    if status == "locating":
        _set("locate_phase", "manual_done")
        _set("message", "标记完成，请在网页中确认定位")
        return True
    return False


def stop_grader():
    _set("stop_requested", True)
    _set("message", "正在停止...")


def _wait_until(wait_for, timeout=1800):
    start = time.time()
    while _get("status") == wait_for:
        if _get("stop_requested"):
            return False
        if time.time() - start > timeout:
            return False
        time.sleep(1)
    return not _get("stop_requested") and _get("status") != "error"


def _is_logged_in(driver):
    try:
        url = driver.current_url
        if "login" not in url.lower() and "passport" not in url.lower():
            src = driver.page_source[:3000]
            if any(w in src for w in ["您好", "欢迎", "阅卷", "首页"]):
                return True
        return False
    except Exception:
        return False


# ============ 覆盖层注入 ============


OVERLAY_SCRIPT_TEMPLATE = """
(function(){{
if(window.__aiGraderOverlay) return;
window.__aiGraderOverlay = true;
window.__aiGraderClicks = {{score:null, submit:null}};
var API_BASE = '{api_base}';

var overlay = document.createElement('div');
overlay.id = '__aiGraderOverlay';
overlay.innerHTML = `
<style>
#__aiGraderOverlay{{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:2147483646;display:flex;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue',sans-serif}}
.__ago-bg{{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,113,227,.06);pointer-events:none}}
.__ago-hdr{{position:relative;background:rgba(0,0,0,.82);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);color:#fff;padding:14px 20px;text-align:center;font-size:15px;font-weight:500;z-index:1;letter-spacing:-.01em}}
.__ago-hdr small{{display:block;color:rgba(255,255,255,.55);font-size:12px;margin-top:4px;font-weight:400}}
.__ago-mid{{flex:1;position:relative;cursor:crosshair}}
.__ago-marker{{position:absolute;width:24px;height:24px;pointer-events:none;transform:translate(-50%,-50%)}}
.__ago-marker::before,.__ago-marker::after{{content:'';position:absolute;background:#0071e3}}
.__ago-marker::before{{width:2px;height:24px;left:11px;top:0}}
.__ago-marker::after{{width:24px;height:2px;top:11px;left:0}}
.__ago-marker .__ago-ring{{position:absolute;width:32px;height:32px;border:2.5px solid #0071e3;border-radius:50%;transform:translate(-50%,-50%);animation:__agoPulse 2s ease-in-out infinite}}
.__ago-marker .__ago-lbl{{position:absolute;top:-24px;left:50%;transform:translateX(-50%);background:#0071e3;color:#fff;font-size:11px;font-weight:500;padding:2px 8px;border-radius:6px;white-space:nowrap;letter-spacing:.02em}}
@keyframes __agoPulse{{0%,100%{{opacity:1;transform:translate(-50%,-50%) scale(1)}}50%{{opacity:.4;transform:translate(-50%,-50%) scale(1.15)}}}}
</style>
<div class="__ago-bg"></div>
<div class="__ago-hdr" id="__agoHdr">请点击打分框位置<small>在页面 app 中完成标记操作</small></div>
<div class="__ago-mid" id="__agoMid"></div>`;
document.body.appendChild(overlay);

function __agoUpdate(){{
var s=window.__aiGraderClicks.score,p=window.__aiGraderClicks.submit;
var hdr=document.getElementById('__agoHdr');
if(s&&p){{hdr.innerHTML='两处已标记<small>可在页面 app 中确认，或继续点击修改位置</small>'}}
else if(s){{hdr.innerHTML='请点击<b>提交按钮</b>位置<small>在页面中点击提交按钮</small>'}}
else{{hdr.innerHTML='请点击<b>打分框</b>位置<small>在页面中点击打分框</small>'}}
}}

function __agoPost(url, data) {{
  return fetch(API_BASE + url, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(data)
  }}).catch(function(err) {{ console.error('[AI改卷] API调用失败:', url, err); }});
}}

overlay.querySelector('#__agoMid').addEventListener('click',function(e){{
var mid=overlay.querySelector('#__agoMid');
var rect=mid.getBoundingClientRect();
// vx,vy = viewport coords for elementFromPoint (correct positioning)
var vx=Math.round(e.clientX),vy=Math.round(e.clientY);
// mx,my = coords relative to __ago-mid for marker display
var mx=Math.round(e.clientX-rect.left),my=Math.round(e.clientY-rect.top);
var clicks=window.__aiGraderClicks;
if(!clicks.score){{
clicks.score={{x:vx,y:vy}};
var m=document.createElement('div');m.className='__ago-marker';m.id='__agoMS';
m.style.left=mx+'px';m.style.top=my+'px';
m.innerHTML='<div class="__ago-ring"></div><div class="__ago-lbl">打分框</div>';
mid.appendChild(m);
__agoPost('/api/auto/mark-score',{{x:vx,y:vy}});
}}else if(!clicks.submit){{
clicks.submit={{x:vx,y:vy}};
var old=document.getElementById('__agoMP');if(old)old.remove();
var m2=document.createElement('div');m2.className='__ago-marker';m2.id='__agoMP';
m2.style.left=mx+'px';m2.style.top=my+'px';
m2.innerHTML='<div class="__ago-ring"></div><div class="__ago-lbl">提交按钮</div>';
mid.appendChild(m2);
__agoPost('/api/auto/mark-submit',{{x:vx,y:vy}});
}}else{{
clicks.score={{x:vx,y:vy}};
clicks.submit=null;
var oldM=document.getElementById('__agoMS');if(oldM)oldM.remove();
var oldP=document.getElementById('__agoMP');if(oldP)oldP.remove();
var m3=document.createElement('div');m3.className='__ago-marker';m3.id='__agoMS';
m3.style.left=mx+'px';m3.style.top=my+'px';
m3.innerHTML='<div class="__ago-ring"></div><div class="__ago-lbl">打分框</div>';
mid.appendChild(m3);
__agoPost('/api/auto/mark-score',{{x:vx,y:vy}});
}}
__agoUpdate();
}});

window.__agoReset=function(){{
window.__aiGraderClicks={{score:null,submit:null}};
var mid=overlay.querySelector('#__agoMid');mid.innerHTML='';
__agoUpdate();
}};
window.__agoGetState=function(){{
var c=window.__aiGraderClicks;
return {{score:c.score,submit:c.submit}};
}};
}})();
"""


def inject_click_overlay():
    """注入覆盖层到主页面和 iframe"""
    driver = _get("driver")
    if not driver:
        return
    # Build the overlay script with the absolute API base URL so that
    # fetch() calls from the target website reach our Flask server.
    overlay_script = OVERLAY_SCRIPT_TEMPLATE.format(api_base="http://127.0.0.1:5000")
    try:
        driver.switch_to.default_content()
        driver.execute_script(overlay_script)
        iframes = driver.find_elements("tag name", "iframe")
        for i in range(len(iframes)):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(i)
                driver.execute_script(overlay_script)
            except Exception:
                pass
        driver.switch_to.default_content()
        print("[overlay] 覆盖层已注入")
    except Exception as e:
        print("[overlay] 注入失败: " + str(e))


def remove_overlay(driver):
    """移除覆盖层"""
    if not driver:
        return
    try:
        driver.switch_to.default_content()
        driver.execute_script("""
            var el = document.getElementById('__aiGraderOverlay');
            if(el) el.remove();
            window.__aiGraderOverlay = false;
        """)
        iframes = driver.find_elements("tag name", "iframe")
        for i in range(len(iframes)):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(i)
                driver.execute_script("""
                    var el = document.getElementById('__aiGraderOverlay');
                    if(el) el.remove();
                    window.__aiGraderOverlay = false;
                """)
            except Exception:
                pass
        driver.switch_to.default_content()
    except Exception:
        pass


def highlight_detected_elements(driver, info):
    """自动模式：高亮检测到的元素"""
    if not driver or not info:
        return
    try:
        driver.switch_to.default_content()
        if info.get("in_iframe") and info.get("iframe_index", -1) >= 0:
            driver.switch_to.frame(info["iframe_index"])
        driver.execute_script("""
            if(!document.getElementById('__aiGraderHL')){
                var s=document.createElement('style');
                s.id='__aiGraderHL';
                s.textContent='.__ai-hl{outline:3px solid #3a7d44!important;background:rgba(58,125,68,.1)!important;transition:outline .2s}';
                document.head.appendChild(s);
            }
        """)
        if info.get("score_element"):
            se = info["score_element"]
            if se.get("x") is not None:
                el = driver.execute_script(
                    "return document.elementFromPoint(arguments[0],arguments[1]);",
                    se["x"] + se.get("w", 0) // 2, se["y"] + se.get("h", 0) // 2
                )
                if el:
                    driver.execute_script("arguments[0].classList.add('__ai-hl')", el)
        if info.get("submit_element"):
            su = info["submit_element"]
            if su.get("x") is not None:
                el = driver.execute_script(
                    "return document.elementFromPoint(arguments[0],arguments[1]);",
                    su["x"] + su.get("w", 0) // 2, su["y"] + su.get("h", 0) // 2
                )
                if el:
                    driver.execute_script("arguments[0].classList.add('__ai-hl')", el)
        driver.switch_to.default_content()
        print("[highlight] 元素已高亮")
    except Exception as e:
        print("[highlight] 高亮失败: " + str(e))


def clear_highlights(driver):
    """清除高亮"""
    if not driver:
        return
    try:
        driver.switch_to.default_content()
        driver.execute_script("""
            var s=document.getElementById('__aiGraderHL');if(s)s.remove();
            document.querySelectorAll('.__ai-hl').forEach(function(e){e.classList.remove('__ai-hl')});
        """)
        iframes = driver.find_elements("tag name", "iframe")
        for i in range(len(iframes)):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(i)
                driver.execute_script("""
                    var s=document.getElementById('__aiGraderHL');if(s)s.remove();
                    document.querySelectorAll('.__ai-hl').forEach(function(e){e.classList.remove('__ai-hl')});
                """)
            except Exception:
                pass
        driver.switch_to.default_content()
    except Exception:
        pass


# ============ 评分截图（保存到文件） ============


def take_screenshot(driver, name):
    ts = datetime.now().strftime("%H%M%S")
    filepath = os.path.join(SCREENSHOT_DIR, name + "_" + ts + ".png")
    driver.save_screenshot(filepath)
    _set("latest_screenshot", filepath)
    return filepath


def encode_local_image(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")


# ============ AI 评分 ============


def ai_grade(reference, max_score, api_key, api_base, model, student_answer=None, image_data=None, is_image=False):
    client = OpenAI(api_key=api_key, base_url=api_base)
    ms = int(max_score)

    if is_image:
        answer_section = ""
        prompt_extra = "请仔细识别图片中学生的手写或打印答案"
    else:
        answer_section = "\n\n## 学生答案\n\n" + student_answer
        prompt_extra = "请根据参考答案对学生答案进行评分"

    prompt = (
        "你是一位教师。" + prompt_extra + "。\n\n"
        "## 参考答案与评分标准\n\n" + reference
        + "\n\n## 评分要求（必须严格遵守）\n\n"
        "- 本题满分: " + str(ms) + " 分\n"
        "- score 必须是 0 到 " + str(ms) + " 之间的整数\n"
        "- max_score 必须填 " + str(ms) + "\n"
        "- 根据学生答案的实际质量打分，不要默认给高分\n\n"
        "请按以下 JSON 格式输出（只输出 JSON）：\n"
        '{"recognized_text":"识别出的学生答案","score":3,"max_score":' + str(ms) + ',"grade":"B+"'
        ',"summary":"一句话评价","correct_points":["正确要点"],"wrong_points":["错误要点"]'
        ',"suggestions":["建议"],"detailed_comment":"详细评语"}\n\n'
        "得分率 = score / " + str(ms) + " * 100%\n"
        "等级: A+(>=95%),A(>=90%),A-(>=85%),B+(>=80%),B(>=75%),B-(>=70%),C+(>=65%),C(>=60%),F(<60%)"
    )
    try:
        if is_image and image_data:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data}},
            ]
        elif student_answer:
            content = prompt + "\n\n## 学生答案\n\n" + student_answer
        else:
            return None

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是专业教师助手。满分" + str(ms) + "分，score不能超过" + str(ms) + "。严格JSON输出。"},
                {"role": "user", "content": content},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        text = response.choices[0].message.content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        data = json.loads(text)
        data["max_score"] = ms
        if data.get("score", 0) > ms:
            data["score"] = ms
        if data.get("score", 0) < 0:
            data["score"] = 0
        return data
    except Exception as e:
        print("[ai] 评分失败: " + str(e))
        return None


# ============ 主运行 ============


def _run(reference, count, browser_type, api_key, api_base, model, max_score, target_url="https://www.zhixue.com"):
    driver = None
    try:
        browser_name = "Edge" if browser_type == "edge" else "Chrome"
        _set("message", "正在启动 " + browser_name + "...")
        driver = create_driver(browser_type)
        if not driver:
            _set("status", "error")
            _set("message", "浏览器启动失败")
            return
        _set("driver", driver)

        _set("message", "正在打开目标网站...")
        driver.get(target_url)
        time.sleep(3)

        if _is_logged_in(driver):
            _set("status", "auto_login_detected")
            _set("message", "检测到已登录，正在自动确认...")
        else:
            _set("status", "login_waiting")
            _set("message", "请在浏览器窗口中登录")

        def watch_login():
            while _get("status") in ("login_waiting", "auto_login_detected"):
                if _get("stop_requested"):
                    return
                try:
                    if _is_logged_in(driver):
                        _set("status", "auto_login_detected")
                        _set("message", "检测到已登录，正在自动确认...")
                        break
                except Exception:
                    pass
                time.sleep(2)

        threading.Thread(target=watch_login, daemon=True).start()

        if not _wait_until("login_waiting", 1800):
            if _get("status") == "auto_login_detected":
                if not _wait_until("auto_login_detected", 1800):
                    _set("status", "stopped")
                    _set("message", "已取消")
                    return
            else:
                _set("status", "stopped")
                _set("message", "已取消")
                return

        _set("status", "page_waiting")
        _set("message", "请在浏览器中进入阅卷页面，完成后在网页中点击「页面就绪」")

        if not _wait_until("page_waiting", 1800):
            _set("status", "stopped")
            _set("message", "已取消")
            return

        _set("status", "detecting")
        _set("message", "正在分析页面...")

        finder = ElementFinder(driver)
        _set("finder", finder)
        locate_mode = _get("locate_mode")

        if locate_mode == "auto":
            finder.auto_detect_score_input()
            finder.auto_detect_submit_button()
            info = finder.get_detected_info()
            _set("detected_info", info)
            highlight_detected_elements(driver, info)
            _set("status", "locating")
            _set("locate_phase", "auto_confirm")
            _set("message", "自动检测完成，浏览器页面已高亮标记，请确认")

            while _get("status") == "locating" and not _get("stop_requested"):
                phase = _get("locate_phase")
                if phase == "re_detecting":
                    clear_highlights(driver)
                    finder.auto_detect_score_input()
                    finder.auto_detect_submit_button()
                    info = finder.get_detected_info()
                    _set("detected_info", info)
                    highlight_detected_elements(driver, info)
                    _set("locate_phase", "auto_confirm")
                    _set("message", "重新检测完成，请确认")
                elif phase == "confirmed":
                    break
                time.sleep(0.5)
        else:
            _set("status", "locating")
            _set("locate_phase", "manual_mark_score")
            _set("message", "正在注入标记工具...")
            _set("score_pos", None)
            _set("submit_pos", None)
            inject_click_overlay()
            _set("message", "请在浏览器页面中点击打分框位置")

            while _get("status") == "locating" and not _get("stop_requested"):
                phase = _get("locate_phase")
                if phase == "confirmed" or _get("status") == "locate_confirmed":
                    break
                elif phase == "manual_done":
                    # Re-check phase after acquiring lock to avoid race with confirm_locate()
                    if _get("locate_phase") == "confirmed":
                        break
                    sp = _get("score_pos")
                    bp = _get("submit_pos")
                    if sp and bp:
                        finder.set_manual_score(sp["x"], sp["y"])
                        finder.set_manual_submit(bp["x"], bp["y"])
                    if _get("locate_phase") == "confirmed":
                        break
                    _set("locate_phase", "awaiting_confirm")
                    _set("message", "标记完成，请在网页中确认定位")
                elif phase == "re_detecting":
                    _set("score_pos", None)
                    _set("submit_pos", None)
                    inject_click_overlay()
                    _set("locate_phase", "manual_mark_score")
                    _set("message", "已重新注入标记工具，请在浏览器页面中点击打分框位置")
                time.sleep(0.5)

        if _get("stop_requested"):
            return

        clear_highlights(driver)

        # ========== 批改前预验证：确认标记坐标仍然有效 ==========
        if locate_mode == "manual":
            _set("message", "正在验证标记坐标...")
            print("[auto] 预验证标记坐标...")
            try:
                # 滚动到顶部，确保视口坐标与标记时一致
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.5)
                # 验证打分框坐标
                sp = _get("score_pos")
                if sp:
                    el = driver.execute_script(
                        "return document.elementFromPoint(arguments[0], arguments[1]);",
                        sp["x"], sp["y"]
                    )
                    if el:
                        tag = el.tag_name.lower()
                        cls = el.get_attribute("className") or ""
                        print("[预验证] 打分框坐标 (" + str(sp["x"]) + ", " + str(sp["y"]) + "): "
                              "<" + tag + "> class='" + cls[:50] + "'")
                        if "__aiGrader" in cls or "__ago" in cls:
                            _set("status", "error")
                            _set("message", "打分框坐标处仍是覆盖层，请重新标记（覆盖层未完全移除）")
                            return
                    else:
                        print("[预验证] 警告：打分框坐标处无元素")
                # 验证提交按钮坐标
                bp = _get("submit_pos")
                if bp:
                    el = driver.execute_script(
                        "return document.elementFromPoint(arguments[0], arguments[1]);",
                        bp["x"], bp["y"]
                    )
                    if el:
                        tag = el.tag_name.lower()
                        cls = el.get_attribute("className") or ""
                        print("[预验证] 提交按钮坐标 (" + str(bp["x"]) + ", " + str(bp["y"]) + "): "
                              "<" + tag + "> class='" + cls[:50] + "'")
                        if "__aiGrader" in cls or "__ago" in cls:
                            _set("status", "error")
                            _set("message", "提交按钮坐标处仍是覆盖层，请重新标记（覆盖层未完全移除）")
                            return
                    else:
                        print("[预验证] 警告：提交按钮坐标处无元素")
                print("[预验证] 标记坐标验证通过")
            except Exception as e:
                print("[预验证] 验证出错: " + str(e))
                # 验证出错不阻断流程，继续尝试批改

        _set("status", "running")
        _set("message", "开始批改（满分" + str(max_score) + "分）...")
        results = []

        max_retry = 2

        for i in range(count):
            if _get("stop_requested"):
                break

            name = "学生" + str(i + 1)
            _set("progress", i)

            last_error = ""
            for attempt in range(1, max_retry + 2):
                if _get("stop_requested"):
                    break

                if attempt > 1:
                    _set("message", name + " 第" + str(attempt) + "次重试：刷新页面...")
                    print("[auto] " + name + " 第" + str(attempt) + "次重试")
                    try:
                        driver.refresh()
                    except Exception:
                        pass
                    time.sleep(4)
                    try:
                        finder.re_detect()
                    except Exception:
                        pass
                    time.sleep(2)

                _set("message", name + " (" + str(i + 1) + "/" + str(count) + ") 截图中...")
                time.sleep(3)

                try:
                    path = take_screenshot(driver, name)
                except Exception:
                    last_error = "截图失败"
                    continue

                _set("message", name + " AI 识别评分中...")
                image_data = encode_local_image(path)
                current_ref = _get("reference")
                result = ai_grade(current_ref, max_score, api_key, api_base, model, image_data=image_data, is_image=True)

                if not result:
                    last_error = "AI评分失败"
                    continue

                score = result.get("score", 0)
                summary = result.get("summary", "")
                results.append({"student": name, "success": True, "data": result})
                _set("message", name + " 得分: " + str(score) + "/" + str(max_score) + " - " + summary)
                _set("results", results)

                time.sleep(1)
                try:
                    if locate_mode == "manual":
                        # 手动模式：用标记的坐标填分和提交
                        # 先滚动到顶部，确保视口坐标与标记时一致
                        driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(0.5)
                        print("[auto] " + name + " 开始填分 (score=" + str(score) + ")")
                        finder.fill_score_manual(driver, score)
                        time.sleep(0.8)
                        print("[auto] " + name + " 开始提交")
                        finder.click_submit_manual(driver)
                    else:
                        # 自动模式：重新检测元素后填分和提交
                        finder.re_detect()
                        finder.fill_score(driver, score)
                        time.sleep(0.8)
                        finder.click_submit(driver)
                    time.sleep(3)
                    last_error = ""
                    print("[auto] " + name + " 填分提交成功")
                    break
                except Exception as e:
                    last_error = "填分失败: " + str(e)
                    print("[auto] " + name + " " + last_error)
                    # 移除刚才添加的结果（因为填分失败，不能算成功）
                    results.pop()
                    _set("results", results)
                    continue

            if last_error:
                results.append({"student": name, "success": False, "error": last_error})
                _set("message", name + " " + last_error + "（已重试" + str(max_retry) + "次）")
                _set("results", results)

            _set("progress", i + 1)
            time.sleep(2)

        # Save results if any grading was done
        ok = [r for r in results if r.get("success")]
        avg = sum(r["data"]["score"] for r in ok) / len(ok) if ok else 0

        if results:
            result_file = os.path.join(SCREENSHOT_DIR, "results.json")
            try:
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print("[auto] 保存结果失败: " + str(e))

            scores = [r["data"]["score"] for r in ok]
            session_data = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total": count,
                "success": len(ok),
                "avg_score": round(avg, 1),
                "max_score_val": max(scores) if scores else 0,
                "min_score_val": min(scores) if scores else 0,
                "max_score": max_score,
                "recent_results": results[-20:],
            }
            try:
                with open(RESULTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print("[auto] 保存历史记录失败: " + str(e))

        if _get("stop_requested"):
            _set("status", "stopped")
            _set("message", "已停止。已完成 " + str(len(ok)) + "/" + str(count) + " 份")
        else:
            _set("status", "finished")
            _set("message", "全部完成！成功 " + str(len(ok)) + "/" + str(count) + "，平均分 " + str(round(avg, 1)) + "/" + str(max_score))

    except Exception as e:
        _set("status", "error")
        _set("message", "错误: " + str(e))
        print("[auto] 异常: " + str(e))
    finally:
        # Clean up driver reference to avoid stale references
        _set("finder", None)
