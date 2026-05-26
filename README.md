markdown
markdown
# AI 改卷系统 o_o

基于多模态大模型的智能阅卷系统，支持手动改卷和智学网自动阅卷。

## 功能特性

### 手动改卷
- 上传学生答案文件（文本或图片）
- AI 自动评分，输出等级、评语、正确/错误要点
- 批量导出 CSV 成绩表

### 自动阅卷（智学网）
- 控制浏览器自动打开智学网
- 内嵌浏览器控制台，直接在网页中操作智学网（点击、输入、滚动）
- 实时画面同步（每 0.8 秒刷新）
- AI 识别答题卡图片并评分
- 自动填入分数并提交
- 支持账号密码登录和扫码登录
- 支持 Chrome 和 Edge 浏览器

## 快速开始

### 环境要求
- Python 3.10+
- Chrome 或 Edge 浏览器
- ChromeDriver 或 EdgeDriver（放在项目根目录）

### 安装依赖

```bash
pip install flask openai selenium Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple

配置 API

编辑 config.py：


python
python
API_KEY = "你的 API Key"
API_BASE = "https://api.deepseek.com"  # 或其他兼容 OpenAI 接口的服务
MODEL = "deepseek-chat"                # 或其他支持图片识别的模型

也可以在网页端的「自动阅卷」页面中直接填写 API 配置。


启动

bash
bash
python app.py

访问 
http://127.0.0.1:5000
 （手动改卷）或 
http://127.0.0.1:5000/auto
 （自动阅卷）。


使用流程

手动改卷
1.填写 API 配置（API Key、API 地址、模型名称）
2.输入参考答案与评分标准
3.上传学生答案文件（支持 txt、jpg、png 等）
4.点击「开始批改」
5.查看结果，导出 CSV

自动阅卷
1.填写 API 配置
2.输入参考答案与评分标准
3.设置满分分值和批改份数
4.点击「开始自动阅卷」
5.在内嵌浏览器控制台中操作智学网登录
6.点击「已登录」→ 进入阅卷页面 → 点击「页面就绪」
7.系统自动截图 → AI 识别评分 → 填分 → 提交 → 下一份

项目结构

text
text
ai-grader/
├── app.py              # Flask 主程序
├── config.py           # API 配置
├── grader.py           # 手动改卷评分模块
├── auto_grader.py      # 自动阅卷模块（远程控制 + AI 评分）
├── browser_manager.py  # 浏览器管理（启动/关闭/最大化）
├── element_finder.py   # 页面元素定位（评分框/提交按钮）
├── templates/
│   ├── index.html      # 手动改卷页面
│   └── auto.html       # 自动阅卷页面（含内嵌浏览器控制台）
├── screenshots/        # 截图存储目录
├── chrome_profile/     # Chrome 用户数据目录
└── edge_profile/       # Edge 用户数据目录

支持的 AI 模型

系统使用 OpenAI 兼容接口，支持以下模型：


模型	说明
豆包 (doubao)	字节跳动，支持图片识别
DeepSeek	支持图片识别（需使用对应版本）
其他 OpenAI 兼容模型	任何支持 chat/completions 接口的模型

注意：模型必须支持图片（多模态）识别，否则无法识别答题卡图片。


常见问题

Edge/Chrome 启动失败
关闭所有使用相同 profile 的浏览器窗口后重试。系统会自动清理残留进程。


元素定位失败
点击「页面就绪」前，请确保已进入具体的批改界面（能看到答题卡图片和评分区域）。


AI 评分不准确
检查参考答案是否完整
调整评分标准描述
确保答题卡图片清晰
