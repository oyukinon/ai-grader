"""
手动改卷评分模块
"""

from openai import OpenAI
import base64


def encode_image(image_file):
    image_file.seek(0)
    data = image_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = image_file.filename.rsplit(".", 1)[-1].lower()
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "bmp": "image/bmp"}
    mime = mime_map.get(ext, "image/jpeg")
    return "data:" + mime + ";base64," + b64, mime


def grade_answer(api_key, api_base, model, reference, student_answer=None, image_data=None, is_image=False, max_score=100):
    client = OpenAI(api_key=api_key, base_url=api_base)
    max_score = int(max_score)
    prompt = (
        "你是一位教师。请根据参考答案对学生答案进行评分。\n\n"
        "## 参考答案与评分标准\n\n" + reference
        + "\n\n## 评分要求\n\n"
        "- 本题满分: " + str(max_score) + " 分\n"
        "- score 必须是 0 到 " + str(max_score) + " 之间的整数\n"
        "- max_score 必须填 " + str(max_score) + "\n\n"
        "请按 JSON 格式输出：\n"
        '{"recognized_text":"学生答案","score":3,"max_score":' + str(max_score) + ',"grade":"B+"'
        ',"summary":"评价","correct_points":["正确"],"wrong_points":["错误"]'
        ',"suggestions":["建议"],"detailed_comment":"详细评语"}\n\n'
        "得分率 = score / " + str(max_score) + " * 100%\n"
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
            return {"success": False, "error": "无内容"}
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是教师助手。严格按指定JSON格式输出，score不超过" + str(max_score) + "。"},
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
        import json
        data = json.loads(text)
        # 强制修正 max_score
        data["max_score"] = max_score
        if data.get("score", 0) > max_score:
            data["score"] = max_score
        if data.get("score", 0) < 0:
            data["score"] = 0
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}
