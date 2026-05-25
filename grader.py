"""
AI 改卷核心逻辑 — 负责调用 AI 接口进行评分
"""
from openai import OpenAI
def build_prompt(reference_answer: str, student_answer: str) -> str:
    """构建发送给 AI 的改卷提示词"""

    prompt = f"""你是一位严格而公正的教师。请根据参考答案和评分标准，对学生的答案进行批改。

参考答案与评分标准:{reference_answer}
学生答案:{student_answer}
要求请按以下 JSON 格式输出结果（不要输出其他内容）：

json
{{
     "score": 85,
     "max_score": 100,
     "grade": "B+",
     "summary": "总体评价（一句话）",
     "correct_points": ["回答正确的要点1", "正确的要点2"],
     "wrong_points": ["错误或缺失的要点1", "错误的要点2"],
     "suggestions": ["改进建议1", "改进建议2"],
     "detailed_comment": "详细的批改意见，逐条分析学生答案的优缺点"
}}
"""
    return  prompt


from openai import OpenAI
import json

def grade_answer(api_key: str, api_base: str, model: str, reference_answer: str, student_answer: str) -> dict:
    """调用AI API 进行改卷，返回评分结果"""
    client = OpenAI(api_key=api_key, base_url=api_base)
    prompt = build_prompt(reference_answer, student_answer)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一位专业的教师助手，擅长客观公正地批改试卷。请严格按 JSON 格式输出。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        content = response.choices[0].message.content.strip()
        # 去除代码块标记
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)
        return {"success": True, "data": result}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"AI 返回格式错误: {e}", "raw": content}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == '__main__':
    qq = build_prompt('刘念大魔王','刘念是呆子')
    grade_answer()
    print(qq)