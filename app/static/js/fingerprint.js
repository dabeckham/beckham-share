/* Lightweight browser fingerprint for abuse review (not a security control).
   Gathers stable, non-identifying signals and a canvas/WebGL hash, then exposes
   window.BSFP.get() -> { hash, components }. */
(function () {
  function canvasHash() {
    try {
      var c = document.createElement("canvas");
      c.width = 240; c.height = 60;
      var ctx = c.getContext("2d");
      ctx.textBaseline = "top";
      ctx.font = "14px 'Arial'";
      ctx.fillStyle = "#069"; ctx.fillRect(2, 2, 180, 30);
      ctx.fillStyle = "#f60"; ctx.fillText("beckham.ai ☁ share", 4, 4);
      return c.toDataURL().slice(-96);
    } catch (e) { return "na"; }
  }

  function webglInfo() {
    try {
      var gl = document.createElement("canvas").getContext("webgl");
      if (!gl) return "na";
      var dbg = gl.getExtension("WEBGL_debug_renderer_info");
      return dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "webgl";
    } catch (e) { return "na"; }
  }

  function components() {
    var n = navigator || {};
    return {
      ua: n.userAgent,
      lang: n.language,
      langs: (n.languages || []).join(","),
      platform: n.platform,
      cores: n.hardwareConcurrency,
      mem: n.deviceMemory,
      touch: n.maxTouchPoints,
      tz: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone,
      tzoff: new Date().getTimezoneOffset(),
      screen: [screen.width, screen.height, screen.colorDepth, window.devicePixelRatio].join("x"),
      canvas: canvasHash(),
      webgl: webglInfo()
    };
  }

  function djb2(str) {
    var h = 5381;
    for (var i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
    return ("00000000" + h.toString(16)).slice(-8);
  }

  window.BSFP = {
    get: function () {
      var c = components();
      var hash = djb2(JSON.stringify(c));
      return { hash: hash, components: c };
    }
  };
})();
