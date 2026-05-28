# AI 改卷系统 — 手动标记模式完整流程图

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器 (auto.html)                     │
│  ┌──────────┐    轮询 /api/auto/status     ┌──────────────────┐ │
│  │ 前端界面  │ ◄─────── 每 1.5 秒 ─────────► │  Flask 后端       │ │
│  └──────────┘                               │  (app.py)        │ │
│       │ 点击按钮                             └────────┬─────────┘ │
│       ▼                                              │           │
│  POST /api/auto/* ──────────────────────────────────►│           │
└──────────────────────────────────────────────────────┼───────────┘
                                                       │
                                                       ▼
                                    ┌──────────────────────────────┐
                                    │     auto_grader.py           │
                                    │  ┌────────────────────────┐  │
                                    │  │  后台批改线程 (_run)    │  │
                                    │  │  - 启动浏览器           │  │
                                    │  │  - 注入覆盖层           │  │
                                    │  │  - 截图 → AI评分 → 填分 │  │
                                    │  └────────────────────────┘  │
                                    └──────────────┬───────────────┘
                                                   │
                                                   ▼
                                    ┌──────────────────────────────┐
                                    │  目标网站 (如智学网)           │
                                    │  ┌────────────────────────┐  │
                                    │  │  Selenium WebDriver    │  │
                                    │  │  - 打开页面             │  │
                                    │  │  - 注入覆盖层脚本       │  │
                                    │  │  - 填分 + 提交          │  │
                                    │  └────────────────────────┘  │
                                    └──────────────────────────────┘
```

## 手动标记模式完整流程

```
用户点击「开始自动阅卷」
        │
        ▼
┌───────────────────┐
│ 1. 启动浏览器      │  create_driver() → 打开 Chrome/Edge
│    打开目标网站    │  driver.get(target_url)
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 2. 等待用户登录    │  status = "login_waiting"
│    用户在浏览器中  │  前端显示「已登录」按钮
│    登录后点击确认  │  ← 轮询检测登录状态
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 3. 等待进入阅卷页  │  status = "page_waiting"
│    用户导航到阅卷  │  前端显示「页面就绪」按钮
│    页面后点击确认  │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 4. 注入覆盖层      │  status = "locating"
│                   │  locate_phase = "manual_mark_score"
│                   │
│  覆盖层脚本:       │  OVERLAY_SCRIPT_TEMPLATE
│  - 绝对 URL 调用  │  fetch('http://127.0.0.1:5000/api/auto/...')
│  - 区分两套坐标   │  vx,vy = 视口坐标（给 API）
│                   │  mx,my = 相对坐标（给标记显示）
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 5. 用户点击打分框  │  覆盖层 click → __agoPost('/api/auto/mark-score')
│                   │  后端 mark_score_pos(x, y)
│                   │  → 保存 score_pos = {x, y}
│                   │  → locate_phase = "manual_mark_submit"
│                   │  前端更新提示：「请点击提交按钮位置」
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 6. 用户点击提交按钮│  覆盖层 click → __agoPost('/api/auto/mark-submit')
│                   │  后端 mark_submit_pos(x, y)
│                   │  → 保存 submit_pos = {x, y}
│                   │  → locate_phase = "manual_done"  ← 关键！
│                   │  前端轮询到 manual_done → 显示「确认定位」按钮
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 7. 用户确认定位    │  前端 POST /api/auto/overlay-done + /api/auto/confirm-locate
│                   │  confirm_locate():
│                   │  → 手动模式下直接设置 finder 坐标（避免竞态）
│                   │  → 移除覆盖层 + 高亮
│                   │  → status = "locate_confirmed"
│                   │  → locate_phase = "confirmed"
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│ 8. 预验证标记坐标  │  滚动到顶部 window.scrollTo(0,0)
│                   │  检查 score_pos 处元素是否是覆盖层残留
│                   │  检查 submit_pos 处元素是否是覆盖层残留
│                   │  如果是覆盖层 → 报错，要求重新标记
└───────┬───────────┘
        │
        ▼
┌───────────────────────────────────────────────────────┐
│ 9. 批改循环 (对每个学生重复)                            │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │ 9a. 截图                                         │  │
│  │     take_screenshot(driver, name)                │  │
│  │     → 保存到 screenshots/ 目录                   │  │
│  └──────────────────┬──────────────────────────────┘  │
│                     ▼                                 │
│  ┌─────────────────────────────────────────────────┐  │
│  │ 9b. AI 识别评分                                  │  │
│  │     ai_grade(reference, max_score, image_data)  │  │
│  │     → 调用 OpenAI 兼容 API                       │  │
│  │     → 返回 {score, summary, grade, ...}         │  │
│  └──────────────────┬──────────────────────────────┘  │
│                     ▼                                 │
│  ┌─────────────────────────────────────────────────┐  │
│  │ 9c. 填入分数 (手动模式)                          │  │
│  │     fill_score_manual(driver, score):            │  │
│  │     ① window.scrollTo(0,0) 滚动到顶部           │  │
│  │     ② elementFromPoint(score_pos) 查找元素      │  │
│  │     ③ _validate_element() 验证不是覆盖层        │  │
│  │     ④ 如果是 input → 填入值 + 触发事件          │  │
│  │     ⑤ 如果是按钮   → 点击                       │  │
│  │     ⑥ 验证填入值是否正确                         │  │
│  └──────────────────┬──────────────────────────────┘  │
│                     ▼                                 │
│  ┌─────────────────────────────────────────────────┐  │
│  │ 9d. 点击提交 (手动模式)                          │  │
│  │     click_submit_manual(driver):                 │  │
│  │     ① elementFromPoint(submit_pos) 查找元素     │  │
│  │     ② _validate_element() 验证不是覆盖层        │  │
│  │     ③ 点击（失败时用 JS click 兜底）             │  │
│  └──────────────────┬──────────────────────────────┘  │
│                     ▼                                 │
│  ┌─────────────────────────────────────────────────┐  │
│  │ 9e. 失败重试                                     │  │
│  │     如果填分/提交异常：                           │  │
│  │     → 打印详细错误日志                           │  │
│  │     → 刷新页面 → 重新检测 → 重试（最多 2 次）    │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────┬───────────────────────┘
                                │
                                ▼
                    ┌───────────────────┐
                    │ 10. 批改完成       │  status = "finished"
                    │     保存结果       │  保存到 screenshots/results.json
                    │     显示统计       │  保存到 screenshots/last_session.json
                    └───────────────────┘
```

## 已修复的 Bug 和改进

### Bug 1: 打开 2 个浏览器窗口
```
原因：Flask debug=True 时 reloader fork 子进程，Timer 在父子进程中各执行一次
修复：app.run(debug=True, use_reloader=False) 禁用 reloader
```

### Bug 2: 覆盖层 API 调用失败（确认按钮不出现）
```
原因：覆盖层注入在目标网站（如 zhixue.com），fetch('/api/auto/...') 是相对 URL
      → 请求发到了 zhixue.com 而不是 localhost:5000 → 静默失败

修复：
  ① 改用绝对 URL：fetch('http://127.0.0.1:5000/api/auto/mark-score')
  ② Flask 添加 CORS 头（允许跨域请求）
  ③ Flask 添加 OPTIONS 预检处理
```

### Bug 3: 覆盖层标记位置偏移
```
原因：标记用视口坐标设置 style.left/top，但标记在 __ago-mid（position:relative）内
      → 标记向下偏移了一个 header 的高度

修复：区分两套坐标
  vx,vy = 视口坐标（e.clientX, e.clientY）→ 发给 API → elementFromPoint 使用
  mx,my = 相对坐标（e.clientX-rect.left） → 设置标记显示位置
```

### Bug 4: mark_submit_pos 不推进阶段
```
原因：mark_submit_pos() 设置 submit_pos 后没有改变 locate_phase
      → 前端永远看不到 manual_done → 确认按钮永远不出现

修复：mark_submit_pos() 中添加 _set("locate_phase", "manual_done")
```

### 改进 1: 填分/提交前预验证
```
批改开始前检查标记坐标处的元素：
  - 如果是覆盖层残留 → 报错，要求重新标记
  - 如果元素不存在 → 打印警告
```

### 改进 2: 填分操作增加验证
```
fill_score_manual() 改进：
  - 验证元素不是覆盖层残留
  - 填入后验证值是否正确
  - 详细日志输出
```

### 改进 3: 批改前滚动到顶部
```
每次填分前执行 window.scrollTo(0, 0)
确保视口坐标与标记时一致（避免页面滚动导致坐标偏移）
```

## 关键数据流

```
覆盖层点击 → API (POST) → mark_score_pos/mark_submit_pos
                ↓
         _state["score_pos"] = {x: vx, y: vy}  ← 视口坐标
         _state["locate_phase"] 推进
                ↓
         前端轮询 → 根据 locate_phase 更新 UI
                ↓
         confirm_locate() → finder.set_manual_score(x, y)
                ↓
         填分时 → elementFromPoint(score_pos.x, score_pos.y)
                ↓
         找到元素 → 填入分数 / 点击提交
```

## 坐标系统说明

```
视口坐标 (viewport coordinates):
  - e.clientX, e.clientY
  - 相对于浏览器可视区域左上角
  - elementFromPoint() 使用此坐标
  - 不受页面滚动影响（但滚动后元素位置会变）

覆盖层标记坐标:
  - vx = e.clientX（视口 X）→ 发给 API → 用于 elementFromPoint
  - vy = e.clientY（视口 Y）→ 发给 API → 用于 elementFromPoint
  - mx = e.clientX - rect.left（相对于 __ago-mid）→ 用于标记显示
  - my = e.clientY - rect.top（相对于 __ago-mid）→ 用于标记显示

⚠️ 重要：标记后如果页面发生滚动，视口坐标对应的元素会改变！
   所以每次填分前都要执行 window.scrollTo(0, 0) 滚动到顶部。
```
