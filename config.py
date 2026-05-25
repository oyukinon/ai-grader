"""
配置文件 — 在这里设置你的 API 信息
也可以在网页界面中填写，无需修改此文件
"""

# OpenAI API Key（替换为你自己的）
API_KEY = ""

# API 地址（如果使用第三方兼容服务，修改此处）
API_BASE = "https://api.openai.com/v1"

# 使用的模型
MODEL = "gpt-4o"

# 上传文件大小限制（单位：MB）
MAX_UPLOAD_SIZE = 10

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {"txt", "md"}
