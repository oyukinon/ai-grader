# 📝 AI 智能改卷系统

一个基于 AI 的自动改卷工具，帮助教师快速批改学生作业和考试答案。

## ✨ 功能特点

- 📤 批量上传学生答案文件（支持 `.txt` 和 `.md` 格式）
- 🎯 教师提供参考答案和评分标准
- 🤖 AI 自动评分 + 详细批改意见
- 📊 结果导出为 CSV 表格
- 🌐 简洁美观的 Web 界面

## 🚀 快速开始

### 1. 安装 Python

前往 [python.org](https://www.python.org/downloads/) 下载并安装 Python 3.9 或更高版本。

> ⚠️ 安装时务必勾选 **"Add Python to PATH"** 选项！

### 2. 下载本项目

```bash
git clone https://github.com/你的用户名/ai-grader.git
cd ai-grader
或者直接在 GitHub 页面点击 Code → Download ZIP，解压后进入文件夹。

3. 安装依赖
bash
pip install -r requirements.txt

4. 配置 API Key

打开 config.py，将你的 API Key 填入：


python
python
API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
API_BASE = "https://api.openai.com/v1"
MODEL = "gpt-4o"

5. 运行

bash
bash
python app.py

打开浏览器访问 http://127.0.0.1:5000 即可使用。


📖 使用说明

1.在页面顶部填入 API Key（如已在 config.py 中配置则可跳过）
2.在「参考答案」框中粘贴标准答案和评分标准
3.上传一个或多个学生答案文件
4.点击「开始批改」
5.查看结果，点击「导出 CSV」保存成绩表

📁 文件格式要求

学生答案文件请使用 .txt 格式，每个文件代表一个学生的答案。


文件名即为学生姓名，例如：

张三.txt
李四.txt

⚙️ 技术栈

后端: Python Flask
前端: HTML + CSS + JavaScript
AI: OpenAI GPT-4o API（可替换为其他兼容 API）


