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
from PIL import Image
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
    "locate_mode": "auto",
    "locate_phase": "",
    "detected_info": None,
    "score_pos": None,
    "submit_pos": None,
    "reference": "",
}
_state_lock = threading.Lock()

_fast_screenshot_thread = None
_fast_screenshot_running = False


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
            if k == "driver":
                continue
            if k == "results":
                out[k] = v[-50:]
            else:
                out[k] = v
        out.pop("fast_screenshot", None)
        return out


def start_grader(reference, count, browser_type, api_key, api_base, model, max_score=100, locate_mode="auto"):
    old_driver = _get("driver")
    if old_driver:
        try:
            old_driver.quit()
        except Exception:
            pass
        _set("driver", None)
        time.sleep(1)

    global _fast_screenshot_running
    _fast_screenshot_running = False
    time.sleep(0.5)

    _set("stop_requested", False)
    _set("status", "starting")
    _set("message", "正在启动浏览器...")
    _set("progress", 0)
    _set("total", count)
    _set("reference", reference.strip())
    _set("max_score", int(max_score))
    _set("results", [])
    _set("latest_screenshot", "")
    _set("fast_screenshot", "")
    _set("login_confirmed", False)
    _set("page_confirmed", False)
    _set("locate_mode", locate_mode)
    _set("locate_phase", "")
    _set("detected_info", None)
    _set("score_pos", None)
    _set("submit_pos", None)
    t = threading.Thread(target=_run, args=(reference, count, browser_type, api_key, api_base, model, int(max_score)), daemon=True)
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


def set_locate_mode(mode):
    _set("locate_mode", mode)


def confirm_locate():
    status = _get("status")
    if status == "locating":
        _set("locate_phase", "confirmed")
        _set("status", "locate_confirmed")
        _set("message", "定位已确认，开始批改...")


def redo_locate():
    status = _get("status")
    if status == "locating":
        _set("locate_phase", "re_detecting")
        _set("message", "正在重新检测...")


def update_reference(ref):
    _set("reference", ref.strip())
    print("[auto] 批改标准已更新")


def mark_score_pos(x, y):
    status = _get("status")
    if status == "locating":
        _set("score_pos", {"x": int(x), "y": int(y)})
        phase = _get("locate_phase")
        if phase == "manual_mark_score":
            _set("locate_phase", "manual_mark_submit")
            _set("message", "打分框已标记，请点击提交按钮位置")
        return True
    return False


def mark_submit_pos(x, y):
    status = _get("status")
    if status == "locating":
        _set("submit_pos", {"x": int(x), "y": int(y)})
        _set("message", "提交按钮已标记，请确认或调整")
        return True
    return False


def stop_grader():
    global _fast_screenshot_running
    _fast_screenshot_running = False
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


# ============ 快速截图 ============


_screenshot_mode = "normal"  # "login" | "normal"


def set_screenshot_mode(mode):
    global _screenshot_mode
    _screenshot_mode = mode


def _capture_once(driver):
    """截取一次视口画面，返回 base64 data URL"""
    driver.switch_to.default_content()
    png = driver.get_screenshot_as_png()
    img = Image.open(io.BytesIO(png))
    try:
        vw = driver.execute_script("return window.innerWidth")
        vh = driver.execute_script("return window.innerHeight")
        scale = min(960.0 / vw, 1.0)
        new_w = int(vw * scale)
        new_h = int(vh * scale)
        img = img.crop((0, 0, min(vw, img.width), min(vh, img.height)))
        img = img.resize((new_w, new_h), Image.LANCZOS)
    except Exception:
        img = img.resize((960, 540), Image.LANCZOS)
    quality = 90 if _screenshot_mode == "login" else 75
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return "data:image/jpeg;base64," + b64


def force_screenshot():
    """强制立即截取一次画面"""
    driver = _get("driver")
    if not driver:
        return
    try:
        data = _capture_once(driver)
        _set("fast_screenshot", data)
    except Exception:
        pass


def _start_fast_screenshot(driver):
    """启动后台快速截图线程，登录阶段 0.3s/高质量，正常 0.8s/标准质量"""
    global _fast_screenshot_running, _fast_screenshot_thread
    _fast_screenshot_running = True

    def loop():
        while _fast_screenshot_running:
            try:
                data = _capture_once(driver)
                _set("fast_screenshot", data)
            except Exception:
                pass
            interval = 0.3 if _screenshot_mode == "login" else 0.8
            time.sleep(interval)

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
    _set("latest_screenshot", filepath)
    return filepath


def encode_local_image(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")


# ============ AI 评分（合并自 grader.py） ============


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


# ============ 远程控制 ============


def click_at(x, y):
    driver = _get("driver")
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
    driver = _get("driver")
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
    driver = _get("driver")
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
    driver = _get("driver")
    if not driver:
        return False
    try:
        d = amount if direction == "down" else -amount
        driver.execute_script("window.scrollBy(0, " + str(d) + ")")
        return True
    except Exception:
        return False


def navigate_browser(url):
    driver = _get("driver")
    if not driver:
        return False
    try:
        if not url.startswith("http"):
            url = "https://" + url
        driver.get(url)
        return True
    except Exception:
        return False


def go_back_browser():
    driver = _get("driver")
    if not driver:
        return False
    try:
        driver.back()
        return True
    except Exception:
        return False


def drag(start_x, start_y, end_x, end_y):
    driver = _get("driver")
    if not driver:
        return False
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        driver.switch_to.default_content()
        # 用 JS 获取页面元素，再用 ActionChains 拖拽
        body = driver.find_element("tag name", "body")
        offset_x = int(end_x) - int(start_x)
        offset_y = int(end_y) - int(start_y)
        ActionChains(driver).move_to_element_with_offset(body, int(start_x), int(start_y)).click_and_hold().pause(0.1).move_by_offset(offset_x, offset_y).pause(0.1).release().perform()
        return True
    except Exception as e:
        print("[remote] 拖拽失败: " + str(e))
        return False


# ============ 主运行 ============


def _run(reference, count, browser_type, api_key, api_base, model, max_score):
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

        _set("message", "正在打开智学网...")
        driver.get("https://www.zhixue.com")
        time.sleep(3)

        _start_fast_screenshot(driver)

        try:
            take_screenshot(driver, "login_page")
        except Exception:
            pass

        if _is_logged_in(driver):
            _set("status", "auto_login_detected")
            _set("message", "检测到已登录！点击「已登录」")
        else:
            _set("status", "login_waiting")
            _set("message", "请在浏览器中登录智学网，登录后点击「已登录」")

        set_screenshot_mode("login")

        def watch_login():
            while _get("status") in ("login_waiting", "auto_login_detected"):
                if _get("stop_requested"):
                    return
                try:
                    if _is_logged_in(driver):
                        _set("status", "auto_login_detected")
                        _set("message", "检测到已登录！点击「已登录」")
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

        set_screenshot_mode("normal")
        _set("status", "page_waiting")
        _set("message", "请进入阅卷页面，完成后点击「页面就绪」")

        if not _wait_until("page_waiting", 1800):
            _set("status", "stopped")
            _set("message", "已取消")
            return

        _set("status", "detecting")
        _set("message", "正在分析页面...")
        try:
            take_screenshot(driver, "grading_page")
        except Exception:
            pass

        finder = ElementFinder(driver)
        locate_mode = _get("locate_mode")

        if locate_mode == "auto":
            finder.auto_detect_score_input()
            finder.auto_detect_submit_button()
            info = finder.get_detected_info()
            _set("detected_info", info)
            _set("status", "locating")
            _set("locate_phase", "auto_confirm")
            _set("message", "自动检测完成，请确认定位结果")

            while _get("status") == "locating" and not _get("stop_requested"):
                phase = _get("locate_phase")
                if phase == "re_detecting":
                    finder.auto_detect_score_input()
                    finder.auto_detect_submit_button()
                    info = finder.get_detected_info()
                    _set("detected_info", info)
                    _set("locate_phase", "auto_confirm")
                    _set("message", "重新检测完成，请确认")
                elif phase == "confirmed":
                    break
                time.sleep(0.5)
        else:
            _set("status", "locating")
            _set("locate_phase", "manual_mark_score")
            _set("message", "请点击画面中的打分框位置")
            _set("score_pos", None)
            _set("submit_pos", None)

            while _get("status") == "locating" and not _get("stop_requested"):
                phase = _get("locate_phase")
                if phase == "confirmed":
                    sp = _get("score_pos")
                    bp = _get("submit_pos")
                    if sp and bp:
                        finder.set_manual_score(sp["x"], sp["y"])
                        finder.set_manual_submit(bp["x"], bp["y"])
                    break
                time.sleep(0.5)

        if _get("stop_requested"):
            return

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
                        finder.fill_score_manual(driver, score)
                        time.sleep(1)
                        finder.click_submit_manual(driver)
                    else:
                        finder.re_detect()
                        finder.fill_score(driver, score)
                        time.sleep(1)
                        finder.click_submit(driver)
                    time.sleep(3)
                    last_error = ""
                    break
                except Exception as e:
                    last_error = "填分失败: " + str(e)
                    print("[auto] " + name + " " + last_error)
                    results.pop()
                    _set("results", results)
                    continue

            if last_error:
                results.append({"student": name, "success": False, "error": last_error})
                _set("message", name + " " + last_error + "（已重试" + str(max_retry) + "次）")
                _set("results", results)

            _set("progress", i + 1)
            time.sleep(2)

        _stop_fast_screenshot()

        ok = [r for r in results if r.get("success")]
        avg = sum(r["data"]["score"] for r in ok) / len(ok) if ok else 0
        result_file = os.path.join(SCREENSHOT_DIR, "results.json")
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        _set("status", "finished")
        _set("message", "全部完成！成功 " + str(len(ok)) + "/" + str(count) + "，平均分 " + str(round(avg, 1)) + "/" + str(max_score))

    except Exception as e:
        _set("status", "error")
        _set("message", "错误: " + str(e))
        print("[auto] 异常: " + str(e))
