/* Public share page.

   Two jobs. The Email button opens the visitor's own mail client, because the
   server-side relay is reserved for signed-in members (see the workspace) and
   the public page must never send through our mailbox.

   The other is to identify the browser behind a download. The download stays a
   plain link so right-click-save and download managers keep working, so the
   fingerprint travels two ways: the bundle goes up front as a beacon, and the
   link gains the short hash that ties a later request back to it. A visitor
   whose browser never runs this has no fingerprint on their download, which is
   worth knowing by itself. */
(function () {
  var emailBtn = document.getElementById("emailBtn");
  var linkInput = document.getElementById("shareLink");
  if (emailBtn && linkInput) {
    emailBtn.addEventListener("click", function () {
      window.location.href = window.BS.mailtoLink(linkInput.value);
    });
  }

  var dl = document.getElementById("downloadBtn");
  if (!dl || !window.BSFP) return;
  var token = dl.getAttribute("data-token");
  if (!token) return;

  var fp;
  try {
    fp = window.BSFP.get();
  } catch (e) {
    return;
  }
  if (!fp || !fp.hash) return;

  dl.href += (dl.href.indexOf("?") === -1 ? "?" : "&") + "fp=" + encodeURIComponent(fp.hash);

  var body = JSON.stringify({ hash: fp.hash, components: fp.components });
  var url = "/api/shares/" + encodeURIComponent(token) + "/client";
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, body);
    } else {
      fetch(url, { method: "POST", body: body, keepalive: true });
    }
  } catch (e) {
    /* Reporting is best effort; never let it interfere with the download. */
  }
})();
