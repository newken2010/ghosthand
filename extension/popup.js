/* GhostHand popup 逻辑 */
const $ = (id) => document.getElementById(id);

function bg(cmd, extra) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ cmd, ...extra }, (r) => resolve(r));
  });
}

async function refresh() {
  const st = await bg("getState");
  $("dot").className = "dot " + (st.connected ? "on" : "off");
  $("connText").textContent = st.connected ? "网关已连接" : "网关未连接";
  $("wsBtn").textContent = st.connected ? "断开" : "连接";
  $("dot2").className = "dot " + (st.attached ? "on" : "off");
  $("attachText").textContent = st.attached ? "已附加（trusted 输入就绪）" : "未附加标签";
  $("attachBtn").textContent = st.attached ? " detach" : "附加当前标签";
  if (st.pace) $("pace").value = st.pace;
}

async function refreshTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("tabInfo").textContent = (tab.title || tab.url || "-").slice(0, 80);
}

function log(s) {
  $("actionLog").textContent = s;
}

$("wsBtn").onclick = async () => {
  const url = $("wsUrl").value.trim();
  chrome.storage.local.set({ wsUrl: url });
  await bg("wsConnect", { url });
  setTimeout(refresh, 800);
};

$("attachBtn").onclick = async () => {
  const st = await bg("getState");
  if (st.attached) {
    await bg("detach");
    log("已 detach");
  } else {
    const r = await bg("attach");
    log(r.ok ? `已附加: ${r.url}` : `附加失败: ${r.error}`);
  }
  refresh();
};

$("pace").onchange = async () => {
  const pace = $("pace").value;
  chrome.storage.local.set({ pace });
  await bg("setPace", { pace });
};

$("findHandleBtn").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const r = await chrome.tabs.sendMessage(tab.id, { cmd: "findHandle" }).catch((e) => ({ error: String(e) }));
  if (r && r.error) return log(`错误: ${r.error}`);
  if (!r) return log("未找到滑块柄（DOM 启发式）");
  log(`滑块柄: cx=${Math.round(r.cx)} cy=${Math.round(r.cy)} w=${Math.round(r.width)} h=${Math.round(r.height)}\n目标 x 需由 AI 看图或启发式确定`);
};

$("holdDragBtn").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const h = await chrome.tabs.sendMessage(tab.id, { cmd: "findHandle" }).catch(() => null);
  if (!h) return log("未找到滑块柄，无法演示");
  // 演示：从滑块柄向右拖 300px（真实场景目标由 AI 量出）
  const r = await bg("holdDrag", {
    x0: h.cx, y0: h.cy, x1: h.cx + 300, y1: h.cy, hold: 1.5,
  });
  log(r.ok ? "长按拖动完成（按住 1.5s + 分段拖动）" : `失败: ${r.error}`);
};

chrome.storage.local.get(["wsUrl", "pace"], (r) => {
  if (r.wsUrl) $("wsUrl").value = r.wsUrl;
  if (r.pace) $("pace").value = r.pace;
});
refresh();
refreshTab();