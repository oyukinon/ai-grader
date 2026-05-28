# AI 改卷系统

基于多模态大模型的智能阅卷系统，支持手动改卷和智学网自动阅卷。

## 功能特性

### 手动改卷

- 上传学生答案文件（文本或图片）
- AI 自动评分，输出等级、评语、正确/错误要点
- 批量导出 CSV 成绩表

### 自动阅卷

- 支持自定义目标网址（默认智学网，可更换为其他阅卷平台）
- 控制浏览器自动打开目标网站，自动检测登录状态
- AI 识别答题卡图片并评分，自动填入分数并提交
- 支持自动检测和手动标记两种定位方式
- 支持 Chrome 和 Edge 浏览器
- 批改过程中可随时修改评分标准，后续评分立即生效

### 数据持久化

- API 配置、批改配置自动保存到浏览器本地存储，重启后自动恢复
- 批改结果（统计 + 最近答卷详情）保存到文件，下次启动可查看历史记录

## 开始前的准备

1. 点击 Code → Download ZIP，解压至桌面
2. 下载安装 Python 3.10+
3. 根据你使用的浏览器下载对应驱动，放至项目根目录：
   - Chrome → [ChromeDriver](https://googlechromelabs.github.io/chrome-for-testing/)
   - Edge → [EdgeDriver](https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/)

### 环境要求

- Python 3.10+
- Chrome 或 Edge 浏览器
- ChromeDriver 或 EdgeDriver（放在项目根目录）

### 安装启动

双击项目根目录的 `start.bat` 即可一键完成：

1. 检查 Python 环境
2. 首次运行自动安装依赖（flask、openai、selenium、Pillow）
3. 启动服务并自动打开浏览器

如需手动启动：

```text
pip install flask openai selenium Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
cd C:\Users\你的用户名\Desktop\ai-grader
python app.py
```

浏览器访问：

- http://127.0.0.1:5000 — 手动改卷
- http://127.0.0.1:5000/auto — 自动阅卷（智学网）

## 使用流程

### 自动阅卷

1. 填写 API 配置（API Key、地址、模型名称）
2. 设置目标网址（默认智学网，可更换为其他阅卷平台）
3. 输入参考答案与评分标准
4. 设置满分分值和批改份数，选择浏览器和定位方式
5. 点击「开始自动阅卷」
6. 在浏览器窗口中登录目标网站（如已登录会自动跳过）
6. 进入阅卷页面后点击「页面就绪」
7. 自动定位：确认检测结果；手动标记：在浏览器页面上依次点击打分框和提交按钮位置，然后在页面 app 中确认
8. 系统自动截图 → AI 识别评分 → 填分 → 提交 → 下一份
9. 批改过程中可展开「批改标准」随时修改评分标准

## 项目结构

```text
ai-grader/
├── app.py              # Flask 主程序
├── config.py           # API 配置
├── grader.py           # 手动改卷评分模块
├── auto_grader.py      # 自动阅卷模块（浏览器控制 + AI 评分 + 覆盖层注入）
├── browser_manager.py  # 浏览器管理（启动/关闭/最大化）
├── element_finder.py   # 页面元素定位（评分框/提交按钮）
├── templates/
│   ├── index.html      # 手动改卷页面
│   └── auto.html       # 自动阅卷页面
├── screenshots/        # 截图和批改结果存储
├── chrome_profile/     # Chrome 用户数据目录
└── edge_profile/       # Edge 用户数据目录
```

## 支持的 AI 模型

系统使用 OpenAI 兼容接口，支持以下模型：

| 模型 | 说明 |
| --- | --- |
| 豆包 (doubao) | 字节跳动，支持图片识别 |
| DeepSeek | 支持文本评分 |
| 其他 OpenAI 兼容模型 | 任何支持 chat/completions 接口的模型 |

> 注意：图片识别需要使用支持多模态的模型，否则无法识别答题卡图片。

## 常见问题

### 浏览器启动失败

关闭所有 Chrome/Edge 窗口后重试。系统会自动清理残留进程。

### 元素定位失败

点击「页面就绪」前，确保已进入具体的批改界面（能看到答题卡图片和评分区域）。手动标记模式下，如标记位置有误可点击「重新标记」重新操作。

### AI 评分不准确

- 检查参考答案是否完整
- 调整评分标准描述
- 确保答题卡图片清晰

### 停止后无法重新启动

点击「停止」后等待状态变为「已停止」，启动按钮会自动恢复。如仍有问题，重启 `python app.py`。
