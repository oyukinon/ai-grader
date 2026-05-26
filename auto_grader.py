"""
智学网自动阅卷 — 图片识别 + 远程控制 + 快速实时画面
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

_state = {
    "status": "idle",
    "message": "等待开始",
    "progress": 0,
    "total": 0,
    "max_score": 100,
    "results": [],
    "latest_screenshot": "",
    "fast_screenshot": "",
    "stop_requested": False,
    "driver": None,
    "login_confirmed": False,
    "page_confirmed": False,
}

_fast_screenshot_thread = None
_fast_screenshot_running = False


def get_state():
    out = {}
    for k, v in _state.items():
        if k == "driver":
            continue
        if k == "results":
            out[k] = v[-50:]
        else:
            out[k] = v
    return out


def start_grader(reference, count, browser_type, api_key, api_base, model, max_score=100):
    old_driver = _state.get("driver")
    if old_driver:
        try:
            old_driver.quit()
        except Exception:
            pass
        _state["driver"] = None
        time.sleep(1)

    global _fast_screenshot_running
    _fast_screenshot_running = False
    time.sleep(0.5)

    _state["stop_requested"] = False
    _state["status"] = "starting"
    _state["message"] = "正在启动浏览器..."
    _state["progress"] = 0
    _state["total"] = count
    _state["max_score"] = int(max_score)
    _state["results"] = []
    _state["latest_screenshot"] = ""
    _state["fast_screenshot"] = ""
    _state["login_confirmed"] = False
    _state["page_confirmed"] = False
    t = threading.Thread(target=_run, args=(reference, count, browser_type, api_key, api_base, model, int(max_score)), daemon=True)
    t.start()


def confirm_login():
    _state["login_confirmed"] = True
    if _state["status"] in ("login_waiting", "auto_login_detected"):
        _state["status"] = "login_confirmed"
        _state["message"] = "登录已确认..."


def confirm_ready():
    _state["page_confirmed"] = True
    if _state["status"] in ("page_waiting",):
        _state["status"] = "page_confirmed"
        _state["message"] = "页面已确认，正在分析..."


def stop_grader():
    global _fast_screenshot_running
    _fast_screenshot_running = False
    _state["stop_requested"] = True
    _state["message"] = "正在停止..."


def _wait_until(wait_for, timeout=1800):
    start = time.time()
    while _state["status"] == wait_for:
        if _state["stop_requested"]:
            return False
        if time.time() - start > timeout:
            return False
        time.sleep(1)
    return not _state["stop_requested"] and _state["status"] != "error"


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


# ============ 快速截图 ============


def _start_fast_screenshot(driver):
    """启动后台快速截图线程，每 0.8 秒截一次视口"""
    global _fast_screenshot_running, _fast_screenshot_thread
    _fast_screenshot_running = True

    def loop():
        while _fast_screenshot_running:
            try:
                driver.switch_to.default_content()
                png = driver.get_screenshot_as_png()
                # 压缩：转 JPEG 并缩小
                from PIL import Image
                img = Image.open(io.BytesIO(png))
                # 获取视口大小
                try:
                    vw = driver.execute_script("return window.innerWidth")
                    vh = driver.execute_script("return window.innerHeight")
                    # 缩放到合理大小
                    scale = min(960.0 / vw, 1.0)
                    new_w = int(vw * scale)
                    new_h = int(vh * scale)
                    img = img.crop((0, 0, min(vw, img.width), min(vh, img.height)))
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                except Exception:
                    img = img.resize((960, 540), Image.LANCZOS)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                _state["fast_screenshot"] = "data:image/jpeg;base64," + b64
            except Exception:
                pass
            time.sleep(0.8)

    _fast_screenshot_thread = threading.Thread(target=loop, daemon=True)
    _fast_screenshot_thread.start()
    print("[fast] 快速截图线程已启动")


def _stop_fast_screenshot():
    global _fast_screenshot_running
    _fast_screenshot_running = False


# ============ 评分截图（保存到文件） ============


def take_screenshot(driver, name):
    ts = datetime.now().strftime("%H%M%S")
    filepath = os.path.join(SCREENSHOT_DIR, name + "_" + ts + ".png")
    driver.save_screenshot(filepath)
    _state["latest_screenshot"] = filepath
    return filepath


def encode_local_image(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")


# ============ AI 评分 ============


def ai_grade_image(reference, image_data, api_key, api_base, model, max_score=100):
    client = OpenAI(api_key=api_key, base_url=api_base)
    ms = int(max_score)
    prompt = (
        "你是一位教师。请仔细识别图片中学生的手写或打印答案，"
        "然后根据参考答案和评分标准进行评分。\n\n"
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
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是专业教师助手。满分" + str(ms) + "分，score不能超过" + str(ms) + "。严格JSON输出。"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data}},
                ]},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        data = json.loads(content)
        data["max_score"] = ms
        if data.get("score", 0) > ms:
            data["score"] = ms
        if data.get("score", 0) < 0:
            data["score"] = 0
        return data
    except Exception as e:
        print("[ai] 评分失败: " + str(e))
        return None


# ============ 远程控制 ============


def click_at(x, y):
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        driver.switch_to.default_content()
        ActionChains(driver).move_by_offset(int(x), int(y)).click().perform()
        ActionChains(driver).move_by_offset(-int(x), -int(y)).perform()
        return True
    except Exception as e:
        print("[remote] 点击失败: " + str(e))
        return False


def type_text(text):
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).send_keys(text).perform()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("""
            var el = document.activeElement;
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
                el.value += arguments[0];
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
        """, text)
        return True
    except Exception as e:
        print("[remote] 输入失败: " + str(e))
        return False


def press_key(key):
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        key_map = {
            "enter": Keys.ENTER, "tab": Keys.TAB, "backspace": Keys.BACKSPACE,
            "escape": Keys.ESCAPE, "space": Keys.SPACE,
            "up": Keys.ARROW_UP, "down": Keys.ARROW_DOWN,
            "left": Keys.ARROW_LEFT, "right": Keys.ARROW_RIGHT,
        }
        key_val = key_map.get(key.lower(), key)
        ActionChains(driver).send_keys(key_val).perform()
        return True
    except Exception as e:
        print("[remote] 按键失败: " + str(e))
        return False


def scroll_browser(direction, amount=300):
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        d = amount if direction == "down" else -amount
        driver.execute_script("window.scrollBy(0, " + str(d) + ")")
        return True
    except Exception:
        return False


def navigate_browser(url):
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        if not url.startswith("http"):
            url = "http://" + url
        driver.get(url)
        return True
    except Exception:
        return False


def go_back_browser():
    driver = _state.get("driver")
    if not driver:
        return False
    try:
        driver.back()
        return True
    except Exception:
        return False


# ============ 主运行 ============


def _run(reference, count, browser_type, api_key, api_base, model, max_score):
    driver = None
    try:
        browser_name = "Edge" if browser_type == "edge" else "Chrome"
        _state["message"] = "正在启动 " + browser_name + "..."
        driver = create_driver(browser_type)
        if not driver:
            _state["status"] = "error"
            _state["message"] = "浏览器启动失败"
            return
        _state["driver"] = driver

        _state["message"] = "正在打开智学网..."
        driver.get("http://www.zhixue.com")
        time.sleep(3)

        # 启动快速截图
        _start_fast_screenshot(driver)

        try:
            take_screenshot(driver, "login_page")
        except Exception:
            pass

        if _is_logged_in(driver):
            _state["status"] = "auto_login_detected"
            _state["message"] = "检测到已登录！点击「已登录」"
        else:
            _state["status"] = "login_waiting"
            _state["message"] = "请在浏览器中登录智学网，登录后点击「已登录」"

        def watch_login():
            while _state["status"] in ("login_waiting", "auto_login_detected"):
                if _state["stop_requested"]:
                    return
                try:
                    if _is_logged_in(driver):
                        _state["status"] = "auto_login_detected"
                        _state["message"] = "检测到已登录！点击「已登录」"
                        break
                except Exception:
                    pass
                time.sleep(2)

        threading.Thread(target=watch_login, daemon=True).start()

        if not _wait_until("login_waiting", 1800):
            if _state["status"] == "auto_login_detected":
                if not _wait_until("auto_login_detected", 1800):
                    _state["status"] = "stopped"
                    _state["message"] = "已取消"
                    return
            else:
                _state["status"] = "stopped"
                _state["message"] = "已取消"
                return

        _state["status"] = "page_waiting"
        _state["message"] = "请进入阅卷页面，完成后点击「页面就绪」"

        if not _wait_until("page_waiting", 1800):
            _state["status"] = "stopped"
            _state["message"] = "已取消"
            return

        _state["status"] = "detecting"
        _state["message"] = "正在分析页面..."
        try:
            take_screenshot(driver, "grading_page")
        except Exception:
            pass

        finder = ElementFinder(driver)
        finder.auto_detect_score_input()
        finder.auto_detect_submit_button()

        _state["status"] = "running"
        _state["message"] = "开始批改（满分" + str(max_score) + "分）..."
        results = []

        for i in range(count):
            if _state["stop_requested"]:
                break

            name = "学生" + str(i + 1)
            _state["message"] = name + " (" + str(i + 1) + "/" + str(count) + ") 截图中..."
            _state["progress"] = i
            time.sleep(3)

            try:
                path = take_screenshot(driver, name)
            except Exception as e:
                results.append({"student": name, "success": False, "error": "截图失败"})
                _state["progress"] = i + 1
                _state["results"] = results
                continue

            _state["message"] = name + " AI 识别评分中..."
            image_data = encode_local_image(path)
            result = ai_grade_image(reference, image_data, api_key, api_base, model, max_score)

            if result:
                score = result.get("score", 0)
                summary = result.get("summary", "")
                results.append({"student": name, "success": True, "data": result})
                _state["message"] = name + " 得分: " + str(score) + "/" + str(max_score) + " - " + summary
                _state["results"] = results

                time.sleep(1)
                finder.re_detect()
                finder.fill_score(driver, score)
                time.sleep(1)
                finder.click_submit(driver)
                time.sleep(3)
            else:
                results.append({"student": name, "success": False, "error": "AI评分失败"})
                _state["message"] = name + " AI评分失败"
                _state["results"] = results

            _state["progress"] = i + 1
            time.sleep(2)

        _stop_fast_screenshot()

        ok = [r for r in results if r.get("success")]
        avg = sum(r["data"]["score"] for r in ok) / len(ok) if ok else 0
        result_file = os.path.join(SCREENSHOT_DIR, "results.json")
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        _state["status"] = "finished"
        _state["message"] = "全部完成！成功 " + str(len(ok)) + "/" + str(count) + "，平均分 " + str(round(avg, 1)) + "/" + str(max_score)

    except Exception as e:
        _state["status"] = "error"
        _state["message"] = "错误: " + str(e)
        print("[auto] 异常: " + str(e))
        _state["driver"] = driver
