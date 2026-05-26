"""
AI 改卷系统
"""

import os
import csv
import io
import base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
from grader import grade_answer, encode_image
import config

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_SIZE * 1024 * 1024


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def is_image_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.IMAGE_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/auto")
def auto_page():
    return render_template("auto.html")


@app.route("/api/grade", methods=["POST"])
def api_grade():
    api_key = request.form.get("api_key", "").strip()
    api_base = request.form.get("api_base", "").strip()
    model = request.form.get("model", "").strip()
    reference = request.form.get("reference", "").strip()
    max_score = int(request.form.get("max_score", 100))
    if not api_key:
        return jsonify({"error": "请填写 API Key"}), 400
    if not reference:
        return jsonify({"error": "请填写参考答案"}), 400
    files = request.files.getlist("files")
    valid_files = [f for f in files if f and f.filename and allowed_file(f.filename)]
    if not valid_files:
        return jsonify({"error": "请上传学生答案文件"}), 400
    results = []
    for f in valid_files:
        name = os.path.splitext(f.filename)[0]
        is_img = is_image_file(f.filename)
        if is_img:
            try:
                img, _ = encode_image(f)
            except Exception:
                results.append({"file": f.filename, "student": name, "success": False, "error": "图片读取失败"})
                continue
            result = grade_answer(api_key, api_base, model, reference, image_data=img, is_image=True, max_score=max_score)
        else:
            try:
                content = f.read().decode("utf-8")
            except UnicodeDecodeError:
                try:
                    f.seek(0)
                    content = f.read().decode("gbk")
                except Exception:
                    results.append({"file": f.filename, "student": name, "success": False, "error": "编码错误"})
                    continue
            if not content.strip():
                results.append({"file": f.filename, "student": name, "success": False, "error": "内容为空"})
                continue
            result = grade_answer(api_key, api_base, model, reference, student_answer=content, is_image=False, max_score=max_score)
        if result["success"]:
            results.append({"file": f.filename, "student": name, "success": True, "is_image": is_img, "data": result["data"]})
        else:
            results.append({"file": f.filename, "student": name, "success": False, "is_image": is_img, "error": result.get("error", "未知错误")})
    return jsonify({"results": results})


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json()
    results = data.get("results", [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["学生姓名", "类型", "得分", "满分", "等级", "评价", "正确要点", "错误要点", "建议", "详细评语"])
    for r in results:
        ft = "图片" if r.get("is_image") else "文本"
        if r.get("success") and "data" in r:
            d = r["data"]
            writer.writerow([r.get("student", ""), ft, d.get("score", ""), d.get("max_score", 100), d.get("grade", ""), d.get("summary", ""), ";".join(d.get("correct_points", [])), ";".join(d.get("wrong_points", [])), ";".join(d.get("suggestions", [])), d.get("detailed_comment", "")])
        else:
            writer.writerow([r.get("student", ""), ft, "N/A", "", "", "", "", "", "", r.get("error", "失败")])
    output.seek(0)
    bom = io.BytesIO()
    bom.write(b"\xef\xbb\xbf")
    bom.write(output.getvalue().encode("utf-8"))
    bom.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(bom, mimetype="text/csv", as_attachment=True, download_name="grade_" + ts + ".csv")


@app.route("/api/auto/start", methods=["POST"])
def auto_start():
    import auto_grader
    data = request.get_json()
    reference = data.get("reference", "").strip()
    count = data.get("count", 0)
    browser = data.get("browser", "auto")
    api_key = data.get("api_key", "").strip()
    api_base = data.get("api_base", "").strip()
    model = data.get("model", "").strip()
    max_score = int(data.get("max_score", 100))
    if not api_key:
        return jsonify({"error": "请填写 API Key"}), 400
    if not api_base:
        return jsonify({"error": "请填写 API 地址"}), 400
    if not model:
        return jsonify({"error": "请填写模型名称"}), 400
    if not reference:
        return jsonify({"error": "请填写参考答案"}), 400
    if not count or count < 1:
        return jsonify({"error": "请输入有效的批改人数"}), 400
    state = auto_grader.get_state()
    if state["status"] not in ("idle", "finished", "error", "stopped"):
        return jsonify({"error": "已有任务在运行中"}), 400
    auto_grader.start_grader(reference, count, browser, api_key, api_base, model, max_score)
    return jsonify({"ok": True})


@app.route("/api/auto/status")
def auto_status():
    import auto_grader
    return jsonify(auto_grader.get_state())


@app.route("/api/auto/screenshot")
def auto_screenshot():
    """实时画面 — 优先用快速截图"""
    import auto_grader
    state = auto_grader.get_state()
    # 优先返回快速截图（JPEG，小且快）
    fast = state.get("fast_screenshot", "")
    if fast:
        return jsonify({"image": fast})
    # 备选：评分截图
    path = state.get("latest_screenshot", "")
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("utf-8")
        return jsonify({"image": "data:image/png;base64," + b64})
    return jsonify({"image": ""})



@app.route("/api/auto/confirm-login", methods=["POST"])
def auto_confirm_login():
    import auto_grader
    auto_grader.confirm_login()
    return jsonify({"ok": True})


@app.route("/api/auto/confirm-ready", methods=["POST"])
def auto_confirm_ready():
    import auto_grader
    auto_grader.confirm_ready()
    return jsonify({"ok": True})


@app.route("/api/auto/stop", methods=["POST"])
def auto_stop():
    import auto_grader
    auto_grader.stop_grader()
    return jsonify({"ok": True})


@app.route("/api/remote/click", methods=["POST"])
def remote_click():
    import auto_grader
    data = request.get_json()
    x = int(data.get("x", 0))
    y = int(data.get("y", 0))
    ok = auto_grader.click_at(x, y)
    return jsonify({"ok": ok})


@app.route("/api/remote/type", methods=["POST"])
def remote_type():
    import auto_grader
    data = request.get_json()
    text = data.get("text", "")
    ok = auto_grader.type_text(text)
    return jsonify({"ok": ok})


@app.route("/api/remote/key", methods=["POST"])
def remote_key():
    import auto_grader
    data = request.get_json()
    key = data.get("key", "")
    ok = auto_grader.press_key(key)
    return jsonify({"ok": ok})


@app.route("/api/remote/scroll", methods=["POST"])
def remote_scroll():
    import auto_grader
    data = request.get_json()
    direction = data.get("direction", "down")
    amount = int(data.get("amount", 300))
    ok = auto_grader.scroll_browser(direction, amount)
    return jsonify({"ok": ok})


@app.route("/api/remote/navigate", methods=["POST"])
def remote_navigate():
    import auto_grader
    data = request.get_json()
    url = data.get("url", "")
    ok = auto_grader.navigate_browser(url)
    return jsonify({"ok": ok})


@app.route("/api/remote/back", methods=["POST"])
def remote_back():
    import auto_grader
    ok = auto_grader.go_back_browser()
    return jsonify({"ok": ok})


if __name__ == "__main__":
    print("=" * 50)
    print("  AI 改卷系统 o_o")
    print("  手动改卷: http://127.0.0.1:5000")
    print("  自动阅卷: http://127.0.0.1:5000/auto")
    print("=" * 50)
    app.run(debug=True, port=5000)
