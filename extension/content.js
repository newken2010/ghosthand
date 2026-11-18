/* GhostHand content script —— 页面助手。
 * 提供页面信息读取与状态回读（React 站保命：UI 表象不算数，要回读状态）。
 * 不主动改页面，只响应 background/popup 的查询。 */

(function () {
  if (window.__ghosthandContent) return;
  window.__ghosthandContent = true;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    (async () => {
      try {
        switch (msg.cmd) {
          case "pageInfo": {
            // 可交互元素清单（给 AI/定位用）：按钮/链接/输入框，带坐标
            const els = [...document.querySelectorAll('a, button, input, select, textarea, [role=button], [role=slider]')]
              .filter((e) => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              })
              .slice(0, 100)
              .map((e) => {
                const r = e.getBoundingClientRect();
                return {
                  tag: e.tagName.toLowerCase(),
                  text: (e.innerText || e.value || e.placeholder || '').slice(0, 60),
                  x: Math.round(r.x + r.width / 2),
                  y: Math.round(r.y + r.height / 2),
                  w: Math.round(r.width),
                  h: Math.round(r.height),
                };
              });
            sendResponse({
              url: location.href,
              title: document.title,
              text: (document.body ? document.body.innerText : '').slice(0, 8000),
              elements: els,
            });
            return;
          }
          case "readState": {
            // 状态回读：验证"点击后状态真的进了"（本地踩坑：候选消失≠React 状态进）
            const radios = [...document.querySelectorAll('input[type=radio]')]
              .filter((i) => i.getBoundingClientRect().width > 0);
            const checked = radios.filter((i) => i.checked).map((i) => i.value);
            const disabledBtns = [...document.querySelectorAll('button')]
              .filter((b) => b.getBoundingClientRect().width > 0 && b.disabled)
              .map((b) => (b.innerText || '').slice(0, 30));
            const activeVal = document.activeElement
              ? (document.activeElement.value || '').slice(0, 200)
              : null;
            sendResponse({ checked, disabledBtns, activeVal });
            return;
          }
          case "findHandle": {
            // 滑块柄检测（与 Python slider.py 同款启发式）
            const hints = ['slide', 'slider', 'drag', 'handle', 'verify', 'code-btn', 'captcha'];
            const cands = [...document.querySelectorAll('div, span, i, button, a')].filter((e) => {
              const r = e.getBoundingClientRect();
              if (r.width < 20 || r.width > 120 || r.height < 12 || r.height > 80) return false;
              const cls = (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || '';
              const s = (cls + ' ' + (e.id || '')).toLowerCase();
              return hints.some((h) => s.includes(h));
            });
            if (!cands.length) { sendResponse(null); return; }
            cands.sort((a, b) =>
              b.getBoundingClientRect().width * b.getBoundingClientRect().height -
              a.getBoundingClientRect().width * a.getBoundingClientRect().height);
            const r = cands[0].getBoundingClientRect();
            sendResponse({ x: r.x, y: r.y, width: r.width, height: r.height,
                           cx: r.x + r.width / 2, cy: r.y + r.height / 2 });
            return;
          }
          default:
            sendResponse({ ok: false, error: 'unknown cmd' });
        }
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    })();
    return true;
  });
})();