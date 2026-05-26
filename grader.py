"""
手动改卷评分模块
"""

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
    from auto_grader import ai_grade
    result = ai_grade(reference, max_score, api_key, api_base, model,
                      student_answer=student_answer, image_data=image_data, is_image=is_image)
    if result is None:
        return {"success": False, "error": "AI评分失败"}
    return {"success": True, "data": result}