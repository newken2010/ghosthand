/* GhostHand background service worker
 * 两个职责：
 *  A. WS 客户端：连本地 ghosthand 网关（ws://127.0.0.1:8765），透传 AI 指令、同步状态
 *  B. 纯插件模式：chrome.debugger attach 当前标签，直接发 CDP Input 事件（trusted）
 *     —— 没有 Python 网关时，插件自己就是驱动器。
 *
 * 注意：chrome.debugger 一次只能 attach 一个 target；attach 时目标标签顶部会显示
 * "正在调试"提示。与 Python 网关（Playwright CDP）二选一，不要同时 attach 同一标签。
 */

const GW_DEFAULT = "ws://127.0.0.1:8765";
const state = {
  ws: null,
  wsUrl: GW_DEFAULT,
  connected: false,
  pace: "normal",
  debugTargetId: null, // chrome.debugger 模式附加的标签
  queue: [],
  lastResult: null,
};

/* ---------------- 状态广播给 popup ---------------- */
function broadcast() {
  chrome.runtime.sendMessage({
    type: "state",
    connected: state.connected,
    attached: !!state.debugTargetId,
    pace: state.pace,
    queueLen: state.queue.length,
  }).catch(() => {});
}

/* ---------------- A. WS 网关客户端 ---------------- */
function wsConnect() {
  if (state.ws) {
    try { state.ws.close(); } catch (e) {}
  }
  let ws;
  try {
    ws = new WebSocket(state.wsUrl);
  } catch (e) {
    scheduleReconnect();
    return;
  }
  state.ws = ws;
  ws.onopen = () => {
    state.connected = true;
    broadcast();
    wsSend({ cmd: "ping" });
  };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      state.lastResult = msg;
      if (msg.type === "result" && msg.cmd === "queue_status") {
        state.queue = new Array(msg.data.pending || 0).fill(0);
      }
      broadcast();
    } catch (e) {}
  };
  ws.onclose = () => {
    state.connected = false;
    state.ws = null;
    broadcast();
    scheduleReconnect();
  };
  ws.onerror = () => { ws.close(); };
}

function scheduleReconnect() {
  setTimeout(wsConnect, 3000);
}

function wsSend(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
    return true;
  }
  return false;
}

/* ---------------- B. chrome.debugger 纯插件模式 ---------------- */
function dbgAttach(tabId) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", () => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      state.debugTargetId = tabId;
      injectStealth(tabId);
      broadcast();
      resolve();
    });
  });
}

function dbgDetach() {
  return new Promise((resolve) => {
    if (!state.debugTargetId) return resolve();
    chrome.debugger.detach({ tabId: state.debugTargetId }, () => {
      state.debugTargetId = null;
      broadcast();
      resolve();
    });
  });
}

function dbgSend(method, params) {
  return new Promise((resolve, reject) => {
    if (!state.debugTargetId) return reject(new Error("未附加标签"));
    chrome.debugger.sendCommand({ tabId: state.debugTargetId }, method, params, (r) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(r);
    });
  });
}

/* 拟人轨迹（与 Python 端 human.py 同算法的 JS 版：三次贝塞尔 + ease-in-out + 平滑抖动） */
function bezierPath(x0, y0, x1, y1, rnd) {
  const dist = Math.hypot(x1 - x0, y1 - y0);
  const dur = Math.max(0.08, 0.18 + 0.0011 * dist + (rnd() - 0.5) * 0.12);
  const dx = x1 - x0, dy = y1 - y0, L = dist || 1;
  const nx = -dy / L, ny = dx / L;
  const o1 = (0.06 + rnd() * 0.24) * L * (rnd() < 0.5 ? -1 : 1);
  const o2 = (0.04 + rnd() * 0.18) * L * (rnd() < 0.5 ? -1 : 1);
  const c1 = [x0 + dx * 0.28 + nx * o1, y0 + dy * 0.28 + ny * o1];
  const c2 = [x0 + dx * 0.72 + nx * o2, y0 + dy * 0.72 + ny * o2];
  const n = Math.max(12, Math.min(90, Math.round(dist / 9) + 12));
  let jt = 0, jn = 0;
  const pts = [];
  for (let i = 1; i <= n; i++) {
    const u = i / n, mt = 1 - u;
    jt = 0.75 * jt + (rnd() - 0.5) * 2.2;
    jn = 0.75 * jn + (rnd() - 0.5) * 1.5;
    const bx = mt ** 3 * x0 + 3 * mt ** 2 * u * c1[0] + 3 * mt * u ** 2 * c2[0] + u ** 3 * x1;
    const by = mt ** 3 * y0 + 3 * mt ** 2 * u * c1[1] + 3 * mt * u ** 2 * c2[1] + u ** 3 * y1;
    const ease = u * u * (3 - 2 * u);
    const v = 6 * ease * (1 - ease) + 0.12;
    pts.push({ x: bx + jt, y: by + jn, t: dur / (n * v * 3.2) });
  }
  // 累积时间
  let acc = 0;
  for (const p of pts) { acc += p.t; p.t = acc; }
  return pts;
}

async function humanMove(x, y) {
  const pts = bezierPath(state._pos ? state._pos[0] : x, state._pos ? state._pos[1] : y, x, y, Math.random);
  for (const p of pts) {
    await dbgSend("Input.dispatchMouseEvent", { type: "mouseMoved", x: p.x, y: p.y });
    await sleep(Math.max(0, p.t * 1000 - 4));
  }
  state._pos = [x, y];
}

async function humanClick(x, y) {
  await humanMove(x, y);
  await sleep(80 + Math.random() * 220);
  await dbgSend("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await sleep(60 + Math.random() * 60);
  await dbgSend("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}

async function holdDrag(x0, y0, x1, y1, holdSec) {
  await humanMove(x0, y0);
  await sleep(80 + Math.random() * 250);
  await dbgSend("Input.dispatchMouseEvent", { type: "mousePressed", x: x0, y: y0, button: "left", clickCount: 1 });
  state._pos = [x0, y0];
  // 按住阶段：微动保持活性
  const t0 = Date.now();
  while (Date.now() - t0 < holdSec * 1000) {
    await dbgSend("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: x0 + (Math.random() - 0.5) * 2, y: y0 + (Math.random() - 0.5) * 2,
    });
    await sleep(80 + Math.random() * 70);
  }
  // 拖动：分段变速
  const pts = bezierPath(x0, y0, x1, y1, Math.random);
  const segs = Math.max(3, Math.min(6, Math.round(Math.hypot(x1 - x0, y1 - y0) / 90) + 3));
  const total = pts[pts.length - 1].t;
  let si = 0;
  for (const p of pts) {
    while (si < segs && p.t > (total * (si + 1)) / segs) {
      si++;
      await sleep(50 + Math.random() * 100);
    }
    await dbgSend("Input.dispatchMouseEvent", { type: "mouseMoved", x: p.x, y: p.y });
    await sleep(4);
  }
  await dbgSend("Input.dispatchMouseEvent", { type: "mouseMoved", x: x1, y: y1 });
  await sleep(80 + Math.random() * 170);
  await dbgSend("Input.dispatchMouseEvent", { type: "mouseReleased", x: x1, y: y1, button: "left", clickCount: 1 });
  state._pos = [x1, y1];
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ---------------- stealth 注入（debugger 模式） ---------------- */
function injectStealth(tabId) {
  chrome.scripting.executeScript({
    target: { tabId },
    files: ["stealth.js"],
  }).catch(() => {});
}

/* ---------------- popup 消息入口 ---------------- */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.cmd) {
        case "getState":
          sendResponse({
            connected: state.connected,
            attached: !!state.debugTargetId,
            pace: state.pace,
            queueLen: state.queue.length,
          });
          return;
        case "setPace":
          state.pace = msg.pace;
          broadcast();
          sendResponse({ ok: true });
          return;
        case "wsConnect":
          state.wsUrl = msg.url || GW_DEFAULT;
          wsConnect();
          sendResponse({ ok: true });
          return;
        case "attach": {
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          await dbgAttach(tab.id);
          sendResponse({ ok: true, tabId: tab.id, url: tab.url });
          return;
        }
        case "detach":
          await dbgDetach();
          sendResponse({ ok: true });
          return;
        case "click":
          await humanClick(msg.x, msg.y);
          sendResponse({ ok: true });
          return;
        case "holdDrag":
          await holdDrag(msg.x0, msg.y0, msg.x1, msg.y1, msg.hold || 1.5);
          sendResponse({ ok: true });
          return;
        case "wsSend":
          sendResponse({ ok: wsSend(msg.payload) });
          return;
        default:
          sendResponse({ ok: false, error: "unknown cmd" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // 异步 sendResponse
});

/* ---------------- 启动 ---------------- */
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["wsUrl", "pace"], (r) => {
    if (r.wsUrl) state.wsUrl = r.wsUrl;
    if (r.pace) state.pace = r.pace;
  });
});
chrome.runtime.onStartup.addListener(wsConnect);
wsConnect(); // SW 唤醒即尝试连网关