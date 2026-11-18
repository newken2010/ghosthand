# GhostHand —— 拟人浏览器自动化

**让 AI 操作浏览器时像人：不规则节奏、长按拖动、反检测、批量但限速。**

针对三个核心痛点设计：

| 痛点 | GhostHand 的做法 | 在哪 |
|---|---|---|
| 操作间隔太规律（统一 3 秒一眼假） | 1s/2s/3s/5s 模式循环 + 幅度抖动 + 偶发分心长停 | `ghosthand/human.py` `HumanRhythm` |
| 长按拖动过不去（点一下很快不行） | 按住 1~2s（微动保活）→ 分段变速拖动 → 微调松手 | `plan_hold_drag` + `SliderSolver` |
| AI 批量浏览太快/太像机器 | 批量队列 + human 档限速（2~3 页/分钟）+ 断点续传 | `ghosthand/queue.py` |

## 快速开始

```bash
# 1. Edge/Chrome 以调试端口启动（复用真实登录态）
msedge --remote-debugging-port=9222

# 2. 自检（本地测试页，真实验证长按/trusted/不规则，10 项检查）
python -m ghosthand selftest

# 3. 演示
python examples/01_slider_hold_drag.py     # 长按拖滑块
python examples/02_irregular_rhythm.py     # 不规则间隔序列 + --live 实测
python examples/03_batch_browse.py --n 6 --pace human   # 批量浏览限速
python examples/04_ai_dispatch.py          # AI 派单 WS 全链路
python examples/05_browser_use_agent.py    # browser-use 拟人中间件
```

## 架构

```
┌─────────────────────────────────────────────┐
│ AI（本地 Agent / LLM / 你）                  │
│   ├─ WS 网关协议（server.py, :8765）         │
│   └─ browser-use 中间件（agent.py, 可选）     │
├─────────────────────────────────────────────┤
│ 拟人引擎 human.py（框架无关，只产"计划"）      │
│   不规则节奏 / 贝塞尔轨迹 / 长按 / 打字 / 滚动 │
├─────────────────────────────────────────────┤
│ 驱动器 driver.py                             │
│   attach 模式：CDP 连已开浏览器(9222)         │
│   launch 模式：自带 persistent context       │
│   执行 = CDP Input 域 = trusted 事件          │
├─────────────────────────────────────────────┤
│ 反检测 stealth.py + 浏览器扩展 extension/     │
│   webdriver 抹除 / 指纹一致 / 插件 stealth 注入│
└─────────────────────────────────────────────┘
```

### 为什么必须走 CDP Input 域

现代前端（React 受控输入、滑块验证码）只认真实输入事件：页面内 JS
`dispatchEvent` 是 untrusted，React 的 onChange 经常不响应（本地踩坑：
Fiverr 站 JS 点击"候选消失了但状态没进"）。Playwright 的 `mouse/keyboard`
底层就是 CDP `Input.dispatchMouseEvent`——trusted，且轨迹/节奏完全可控。

### 浏览器扩展（`extension/`）

MV3 插件，两种模式二选一：

1. **AI 网关模式**：本地 `python -m ghosthand serve`，扩展作 WS 客户端透传指令；
2. **纯插件模式**：popup 点"附加当前标签"，扩展用 `chrome.debugger` 自己发
   trusted 输入（内置同款贝塞尔轨迹/长按 JS 实现），没有 Python 也能跑。

安装：Edge/Chrome → `edge://extensions` → 开开发者模式 → 加载已解压的扩展 →
选 `ghosthand/extension`。

## 拟人细节

- **轨迹**：三次贝塞尔 + 控制点垂直随机偏移 + ease-in-out 变速（慢-快-慢）
  + 平滑手抖噪声 + 22% 概率过冲回拉
- **长按**：mousedown 后每 80~150ms 微动 ±1px（保活 + 生理抖动），
  拖动分 3~6 段、段间停顿，速度"启动摩擦→中段快→接近减速"
- **打字**：每键 35~150ms 三角分布、词间稍慢、4% 概率长停顿（想一下）、
  6% 概率打错邻键→停顿→Backspace 改正（真人从不出错反而可疑）
- **滚动**：分段滚 + 阅读停顿 + 18% 概率回滚（刚才没看清）
- **节奏**：`(1,2,3,5)` 循环 × `0.55~1.5` 抖动 + 15% 概率分心长停 2~8s，
  档位倍率 cautious 1.6 / normal 1.0 / brisk 0.55

## 反爬边界（诚实声明）

**做**：抹除自动化自报家门特征（webdriver、空 plugins、缺 chrome 对象）、
指纹一致化（UA/语言/时区/WebGL vendor 对齐）、行为拟人（轨迹/节奏/滚动/
打字）、批量限速与断点续传。

**不做**：
- 不破解验证码**识别**（打码平台/ML 模型的事，与"像人"是两条线；
  GhostHand 只负责"像人地把滑块拖过去"，拖多远由 AI 看图量出）；
- 不对抗设备级风控（账号风控、硬件指纹绑定、IP 信誉）；
- 不承诺 100% 绕过任何站点——拟人化是**降低触发概率**，不是免疫。

## 已验证（本机 Edge 157 + CDP 9222）

`python -m ghosthand selftest` 10/10 通过：

- trusted 事件 `isTrusted=true`
- 长按 2877ms（目标 ≥1200ms）
- 拖动终点误差 1px
- 82 个 move 采样点，轨迹长 342px > 直线 303px（非瞬移）
- 拟人打字入框、击键间隔 15 个不同值
- `navigator.webdriver` 已抹除
- 真实点击 8 次总间隔 `[1.21, 7.88, 8.13, 3.28, 5.5, 6.36, 3.8]s`（7 个间隔 5 个不同值）
- AI 派单 WS 全链路（attach→goto→screenshot→hold_drag→read）通过

## 已知限制与自适应

**CDP 实时性依赖机器负载**。实测本机：空闲时单次 `Input.dispatchMouseEvent`
约 5ms；CPU 满载时劣化到 100~264ms（ Edge CDP 通道被拖慢，非本项目代码问题）。
不自适应时，"按住 1.5s"的计划会录成 9s+，拟人节奏全部失真。

驱动器的对策（`driver._event_cost` / `_auto_points`）：每次会话启动时实测
单事件成本，按"目标人类时长"反推轨迹点数与按住步长——
- 快机器：60+ 采样点，轨迹丝滑；
- 慢机器（264ms/事件）：8 个拖动点、150ms 按住步长，实测按住录得 2.60s，
  仍落在"按住一两秒"的人类范围，终点精度不变（误差 1px）。

**窗口必须可见**：Edge 最小化/后台时 CDP 输入被浏览器节流。驱动器已自动
还原最小化窗口 + `Emulation.setFocusEmulationEnabled`，但请勿手动最小化
正在跑自动化的 Edge 窗口。

## 与现有工具的关系

- **browser-use**（已装 0.12.6）：中间件 monkey patch 其 `Mouse.click/move`、
  `Keyboard.type`，Agent 决策不改，"手"变人手（`ghosthand/agent.py`）
- **Playwright**：本项目的驱动层（`connect_over_cdp` 复用本地 Edge 工作流）
- **BrowserSkill / Kimi 扩展**：可继续用；GhostHand 补它们缺的"拟人"层

## 目录

```
ghosthand/          # Python 包
  human.py          # 拟人引擎（计划生成，框架无关）
  driver.py         # CDP 驱动器（trusted 输入）
  stealth.py        # 反检测补丁
  slider.py         # 滑块专项
  queue.py          # 批量队列（限速+断点续传）
  server.py         # WS 网关
  agent.py          # browser-use 中间件
  cli.py            # 命令行
  selftest.py       # 本地自检
extension/          # MV3 浏览器插件
examples/           # 5 个演示
tests/              # 单元测试（9 项）
```