# GhostHand — Human-Like Browser Automation

**Make AI operate a browser like a human: irregular rhythm, long-press dragging, anti-detection, batch crawling with rate limits.**

Built for three core pain points:

| Pain point | What GhostHand does | Where |
|---|---|---|
| Fixed intervals (uniform 3s is a dead giveaway) | `(1,2,3,5)` cycling pattern + amplitude jitter + occasional distracted long pauses | `ghosthand/human.py` `HumanRhythm` |
| Long-press drag fails (a quick tap is not enough) | Hold 1–2s (micro-movements keep it alive) → segmented variable-speed drag → fine-tune release | `plan_hold_drag` + `SliderSolver` |
| AI browses too fast / too machine-like | Batch queue + human pace limiting (2–3 pages/min) + resumable | `ghosthand/queue.py` |

## Quick start

```bash
# 1. Start Edge/Chrome with a debug port (reuses your real logged-in profile)
msedge --remote-debugging-port=9222

# 2. Self-test (local test page; really verifies long-press / trusted / irregularity, 10 checks)
python -m ghosthand selftest

# 3. Demos
python examples/01_slider_hold_drag.py     # long-press drag a slider
python examples/02_irregular_rhythm.py     # irregular interval sequence + --live
python examples/03_batch_browse.py --n 6 --pace human   # rate-limited batch browsing
python examples/04_ai_dispatch.py          # AI dispatch over WS, full chain
python examples/05_browser_use_agent.py    # browser-use humanization middleware
```

Install: `pip install -e .` (Python 3.10+, playwright). See [INSTALL.md](INSTALL.md) for the per-machine checklist (Python package + MV3 extension).

## Architecture

```
┌─────────────────────────────────────────────┐
│ AI (local agent / LLM / you)                │
│   ├─ WS gateway protocol (server.py, :8765) │
│   └─ browser-use middleware (agent.py, opt.)│
├─────────────────────────────────────────────┤
│ Humanization engine human.py (framework-    │
│   agnostic; produces "plans" only)          │
│   irregular rhythm / bezier paths / hold /  │
│   typing / scrolling                        │
├─────────────────────────────────────────────┤
│ Driver driver.py                            │
│   attach mode: CDP to a running browser(9222│
│   launch mode: own persistent context       │
│   execution = CDP Input domain = trusted    │
├─────────────────────────────────────────────┤
│ Anti-detection stealth.py + extension/      │
│   webdriver wipe / fingerprint consistency /│
│   extension-side stealth injection          │
└─────────────────────────────────────────────┘
```

### Why the CDP Input domain is mandatory

Modern frontends (React controlled inputs, slider captchas) only accept real
input events: in-page JS `dispatchEvent` is untrusted and React's onChange
often ignores it (a local pitfall: on Fiverr, a JS click left the UI updated
but the state unchanged). Playwright's `mouse/keyboard` are CDP
`Input.dispatchMouseEvent` under the hood — trusted, with fully controllable
trajectory and rhythm.

### Browser extension (`extension/`)

MV3 extension, two modes (pick one):

1. **AI gateway mode**: run `python -m ghosthand serve` locally; the extension
   acts as a WS client relaying commands.
2. **Pure extension mode**: popup "attach current tab"; the extension uses
   `chrome.debugger` to send trusted inputs itself (same bezier/long-press JS
   built in), works without Python.

Install: Edge/Chrome → `edge://extensions` → enable Developer mode → Load
unpacked → select `ghosthand/extension`.

## Humanization details

- **Trajectory**: cubic bezier + random perpendicular control-point offset +
  ease-in-out speed (slow-fast-slow) + smooth hand-tremor noise + 22% chance
  of overshoot-and-correct
- **Long-press**: after mousedown, micro-movements of ±1px every 80–150ms
  (keep-alive + physiological tremor); drag in 3–6 segments with pauses
  between; speed profile "startup friction → fast middle → deceleration"
- **Typing**: 35–150ms per key (triangular), slightly slower between words,
  4% chance of a long pause (thinking), 6% chance of hitting a wrong
  neighbor key → pause → Backspace to fix it (a human who never typos is
  suspicious)
- **Scrolling**: segmented scroll + reading pauses + 18% chance of scrolling
  back (didn't catch that)
- **Rhythm**: `(1,2,3,5)` cycle × `0.55–1.5` jitter + 15% chance of a
  distracted 2–8s pause; pace multipliers cautious 1.6 / normal 1.0 /
  brisk 0.55

## Anti-bot boundaries (honest statement)

**What it does**: wipes automation self-reporting signals (webdriver, empty
plugins, missing chrome object), aligns fingerprints (UA/language/timezone/
WebGL vendor), humanizes behavior (trajectory/rhythm/scrolling/typing),
rate-limits batches and supports resumption.

**What it does NOT do**:
- Does not crack captcha *recognition* (that's for captcha-solving services /
  ML models — a separate line from "acting human"; GhostHand only drags the
  slider like a human would; how far to drag is measured by the AI from the
  image)
- Does not fight device-level risk control (account risk, hardware fingerprint
  binding, IP reputation)
- Does not promise 100% bypass of any site — humanization **lowers the
  trigger probability**, it is not immunity

## Verified (local Edge 157 + CDP 9222)

`python -m ghosthand selftest` 10/10 passed:

- trusted events with `isTrusted=true`
- long-press recorded 2877ms (target ≥1200ms)
- drag endpoint error 1px
- 82 move samples, path length 342px > straight-line 303px (no teleport)
- human-like typing into fields, 15 distinct inter-key intervals
- `navigator.webdriver` wiped
- 8 real clicks with total intervals `[1.21, 7.88, 8.13, 3.28, 5.5, 6.36, 3.8]s`
  (7 intervals, 5 distinct values)
- AI dispatch over WS full chain (attach→goto→screenshot→hold_drag→read) passed

## Known limitations & adaptation

**CDP real-time performance depends on machine load.** Measured locally: a
single `Input.dispatchMouseEvent` takes ~5ms when idle; it degrades to
100–264ms under full CPU load (the Edge CDP channel slows down; not a bug in
this project's code). Without adaptation, a planned "hold 1.5s" records as
9s+, and the human rhythm is completely distorted.

The driver's countermeasure (`driver._event_cost` / `_auto_points`): measure
the single-event cost at session start, then derive the number of trajectory
points and hold step size from the "target human duration" —
- fast machine: 60+ samples, silky-smooth trajectory;
- slow machine (264ms/event): 8 drag points, 150ms hold step; measured hold
  recorded 2.60s, still inside the "one to two seconds" human range, endpoint
  precision unchanged (1px error).

**The window must stay visible**: Edge throttles CDP input when minimized or
in the background. The driver automatically restores minimized windows and
enables `Emulation.setFocusEmulationEnabled`, but do not manually minimize an
Edge window while automation is running on it.

## Relationship to existing tools

- **browser-use** (tested with 0.12.6): middleware monkey-patches its
  `Mouse.click/move` and `Keyboard.type`; the agent's decisions are
  untouched, only the "hand" becomes human (`ghosthand/agent.py`)
- **Playwright**: this project's driver layer (`connect_over_cdp` reuses your
  local Edge workflow)
- **BrowserSkill / Kimi extension**: keep using them; GhostHand adds the
  "human-like" layer they lack

## Layout

```
ghosthand/          # Python package
  human.py          # humanization engine (plan generation, framework-agnostic)
  driver.py         # CDP driver (trusted input)
  stealth.py        # anti-detection patches
  slider.py         # slider-specific solver
  queue.py          # batch queue (rate limit + resumable)
  server.py         # WS gateway
  agent.py          # browser-use middleware
  cli.py            # command line
  selftest.py       # local self-test
extension/          # MV3 browser extension
examples/           # 5 demos
tests/              # unit tests (9)
```

中文说明见 [README_zh.md](README_zh.md)。

## License

MIT, see [LICENSE](LICENSE).