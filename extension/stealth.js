/* GhostHand stealth —— 与 Python 端 ghosthand/stealth.py 同源的注入补丁。
 * 由 content_scripts 在 document_start 注入所有页面。
 * 改这里记得同步改 Python 端 STEALTH_JS（反之亦然）。 */
(() => {
  const define = (obj, prop, get) =>
    Object.defineProperty(obj, prop, { get: get, configurable: true });

  // 1) webdriver 标志
  define(navigator, 'webdriver', () => undefined);
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}

  // 2) window.chrome
  if (!window.chrome) {
    window.chrome = {
      runtime: {},
      loadTimes: function () {},
      csi: function () { return { startE: 0, onloadT: 0 }; },
      app: { isInstalled: false },
    };
  }

  // 3) plugins
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

  // 4) languages
  if (!navigator.languages || navigator.languages.length === 0) {
    define(navigator, 'languages', () => ['zh-CN', 'zh', 'en-US', 'en']);
  }

  // 5) 权限查询
  try {
    const origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (p) =>
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(p);
  } catch (e) {}

  // 6) WebGL vendor/renderer
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

  // 7) hairline
  if (window.outerWidth === window.innerWidth && window.outerHeight === window.innerHeight) {
    define(window, 'outerWidth', () => window.innerWidth + 16);
    define(window, 'outerHeight', () => window.innerHeight + 88);
  }

  // 8) 已知自动化变量清理
  for (const k of ['cdc_adoQpoasnfa76pfcZLmcfl_Array', 'cdc_adoQpoasnfa76pfcZLmcfl_Promise',
                   'cdc_adoQpoasnfa76pfcZLmcfl_Symbol', '$cdc_asdjflasutopfhvcZLmcfl_']) {
    try { delete window[k]; } catch (e) {}
  }
})();