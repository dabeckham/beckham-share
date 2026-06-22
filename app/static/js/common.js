/* Shared UI helpers: toast + copy-to-clipboard (delegated via [data-copy]). */
(function () {
  function toast(msg) {
    var t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("show"); });
    setTimeout(function () {
      t.classList.remove("show");
      setTimeout(function () { t.remove(); }, 250);
    }, 1800);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (_) {}
      ta.remove();
      return ok;
    }
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var el = document.querySelector(btn.getAttribute("data-copy"));
    if (!el) return;
    copyText(el.value || el.textContent).then(function (ok) {
      toast(ok ? "Link copied to clipboard" : "Press Ctrl+C to copy");
    });
  });

  function mailtoLink(url, filename) {
    var subject = encodeURIComponent("A file shared with you" + (filename ? ": " + filename : ""));
    var body = encodeURIComponent("Download it here:\n" + url + "\n\nThis link may expire.");
    return "mailto:?subject=" + subject + "&body=" + body;
  }

  window.BS = { toast: toast, copyText: copyText, mailtoLink: mailtoLink };
})();
