# -*- coding: utf-8 -*-
"""GhostHand 反检测层 —— 指纹一致化 + 自动化痕迹抹除。

分层策略（诚实边界见 README）
============================
1. **痕迹层**：抹 ``navigator.webdriver``、补 ``window.chrome``、
   plugins/languages、权限查询、hairline——这些是"这是自动化浏览器"的
   自报家门特征，成本低收益高。
2. **指纹层**：UA / 平台 / 语言 / 时区 与浏览器实际版本对齐；WebGL
   vendor 用真实显卡串；canvas 加"确定性"轻噪声（同一会话内稳定，
   不是每次随机——每次随机本身就是异常）。
3. **行为层**：见 ``human.py``——轨迹/节奏/滚动/打字拟人才是主体，
   指纹只是不拖后腿。
4. **节奏层**：见 ``queue.py``——批量任务限速、URL 间休息。

明确不做（也不该做）的事：
- 不破解验证码识别（那是打码平台/ML 模型的事，与"像人"是两条线）；
- 不对抗设备级风控（账号风控、硬件指纹绑定、IP 信誉）；
- 不承诺 100% 绕过任何站点。拟人化是"降低触发概率"，不是"免疫"。
"""

from __future__ import annotations

from typing import Optional

# 注入页面的 stealth 补丁（与扩展端 stealth.js 同源，改一处记得改两处）
STEALTH_JS = r"""
(() => {
  const define = (obj, prop, get) =>
    Object.defineProperty(obj, prop, { get: get, configurable: true });

  // 1) webdriver 标志
  define(navigator, 'webdriver', () => undefined);
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}

  // 2) window.chrome（headless 模式下缺失是最常见的自动化特征）
  if (!window.chrome) {
    window.chrome = {
      runtime: {},
      loadTimes: function () {},
      csi: function () { return { startE: 0, onloadT: 0 }; },
      app: { isInstalled: false },
    };
  }

  // 3) plugins（headless 的 5 个空 plugins 很显眼）
  if (navigator.plugins.length === 0) {
    const mk = (name, desc, fn, suffix) => {
      const p = Object.create(Plugin.prototype);
      Object.defineProperties(p, {
        name: { get: () => name }, description: { get: () => desc },
        filename: { get: () => fn }, length: { get: () => 1 },
        '0': { get: () => ({ type: suffix, suffixes: suffix, description: desc }) },
      });
      return p;
    };
    const arr = [
      mk('PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', 'pdf'),
      mk('Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', 'pdf'),
      mk('Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', 'pdf'),
      mk('Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer', 'pdf'),
      mk('WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer', 'pdf'),
    ];
    define(navigator, 'plugins', () => arr);
  }

  // 4) languages（headless 有时为空）
  if (!navigator.languages || navigator.languages.length === 0) {
    define(navigator, 'languages', () => ['zh-CN', 'zh', 'en-US', 'en']);
  }

  // 5) 权限查询：Notification.permission 在自动化下行为异常
  try {
    const origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (p) =>
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(p);
  } catch (e) {}

  // 6) WebGL vendor/renderer：统一成常见真实显卡串（按需改）
  try {
    const patchGL = (proto) => {
      const orig = proto.getParameter;
      proto.getParameter = function (p) {
        const UNMASKED_VENDOR = 0x1F00, UNMASKED_RENDERER = 0x1F01;
        if (p === UNMASKED_VENDOR) return 'Google Inc. (Intel)';
        if (p === UNMASKED_RENDERER) return 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)';
        return orig.call(this, p);
      };
    };
    if (window.WebGLRenderingContext) patchGL(window.WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patchGL(window.WebGL2RenderingContext.prototype);
  } catch (e) {}

  // 7) hairline：自动化下 scrollbar 缺失导致 innerWH==outerWH
  if (window.outerWidth === window.innerWidth && window.outerHeight === window.innerHeight) {
    define(window, 'outerWidth', () => window.innerWidth + 16);
    define(window, 'outerHeight', () => window.innerHeight + 88);
  }

  // 8) iframe contentWindow 自检（cdc_ 等变量是已知检测点）
  try {
    const proto = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    // 不重写，仅确保没有常见自动化变量泄漏
    for (const k of ['cdc_adoQpoasnfa76pfcZLmcfl_Array', 'cdc_adoQpoasnfa76pfcZLmcfl_Promise',
                     'cdc_adoQpoasnfa76pfcZLmcfl_Symbol', '$cdc_asdjflasutopfhvcZLmcfl_']) {
      try { delete window[k]; } catch (e) {}
    }
  } catch (e) {}
})();
"""


def launch_args() -> list:
    """反检测启动参数（launch 模式用）。"""
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-default-browser-check",
        "--no-first-run",
        "--no-service-autorun",
        "--password-store=basic",
    ]


def apply_to_page(page) -> None:
    """对已存在页面即时打补丁 + 注册 init script（对新页面持久生效）。

    attach 模式下 playwright-stealth 的 context 级包装不适用（context 已存在），
    所以用 add_init_script + evaluate 双路。
    """
    try:
        page.context.add_init_script(STEALTH_JS)
    except Exception:
        pass
    try:
        page.evaluate(STEALTH_JS)
    except Exception:
        pass


def apply_to_context(context) -> None:
    """对整个 context 注册 init script（launch 模式用）。"""
    try:
        context.add_init_script(STEALTH_JS)
    except Exception:
        pass


def apply_stealth(driver) -> None:
    """驱动器一把梭：attach/launch 后调用。"""
    apply_to_context(driver._context) if driver._context else None
    apply_to_page(driver.page)