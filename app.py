"""
AI 改卷系统 — Flask 主程序
运行方式：python app.py
"""

import os
import csv
import io
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
)
from werkzeug.utils import secure_filename
from grader import grade_answer
import config

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_SIZE * 1024 * 1024

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/grade", methods=["POST"])
def api_grade():
    api_key = request.form.get("api_key", "").strip()
    api_base = request.form.get("api_base", config.API_BASE).strip()
    model = request.form.get("model", config.MODEL).strip()
    reference = request.form.get("reference", "").strip()

    if not api_key:
        return jsonify({"error": "请填写 API Key"}), 400
    if not reference:
        return jsonify({"error": "请填写参考答案"}), 400

    files = request.files.getlist("files")
    valid_files = [f for f in files if f and f.filename and allowed_file(f.filename)]

    if not valid_files:
        return jsonify({"error": "请上传至少一个 .txt 或 .md 格式的学生答案文件"}), 400

    results = []
    for f in valid_files:
        original_name = f.filename
        student_name = os.path.splitext(original_name)[0]

        try:
            content = f.read().decode("utf-8")
        except UnicodeDecodeError:
            try:
                f.seek(0)
                content = f.read().decode("gbk")
            except Exception:
                results.append({
                    "file": original_name,
                    "student": student_name,
                    "success": False,
                    "error": "文件编码错误，请使用 UTF-8 编码",
                })
                continue

        if not content.strip():
            results.append({
                "file": original_name,
                "student": student_name,
                "success": False,
                "error": "文件内容为空",
            })
            continue

        result = grade_answer(api_key, api_base, model, reference, content)

        if result["success"]:
            results.append({
                "file": original_name,
                "student": student_name,
                "success": True,
                "data": result["data"],
            })
        else:
            results.append({
                "file": original_name,
                "student": student_name,
                "success": False,
                "error": result.get("error", "未知错误"),
            })

    return jsonify({"results": results})


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json()
    results = data.get("results", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "学生姓名", "得分", "满分", "等级", "总体评价",
        "正确要点", "错误/缺失要点", "改进建议", "详细评语",
    ])

    for r in results:
        if r.get("success") and "data" in r:
            d = r["data"]
            writer.writerow([
                r.get("student", ""),
                d.get("score", ""),
                d.get("max_score", 100),
                d.get("grade", ""),
                d.get("summary", ""),
                "; ".join(d.get("correct_points", [])),
                "; ".join(d.get("wrong_points", [])),
                "; ".join(d.get("suggestions", [])),
                d.get("detailed_comment", ""),
            ])
        else:
            writer.writerow([
                r.get("student", ""), "N/A", "", "", "", "", "", "",
                r.get("error", "批改失败"),
            ])

    output.seek(0)
    bom_output = io.BytesIO()
    bom_output.write(b"\xef\xbb\xbf")
    bom_output.write(output.getvalue().encode("utf-8"))
    bom_output.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"grade_results_{timestamp}.csv"

    return send_file(
        bom_output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    print("=" * 50)
    print("  AI 智能改卷系统")
    print("  打开浏览器访问: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
