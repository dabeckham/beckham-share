/* Public share page: email button (server send, mailto fallback). */
(function () {
  var emailBtn = document.getElementById("emailBtn");
  if (!emailBtn) return;
  var url = document.getElementById("shareLink").value;
  var token = location.pathname.split("/").pop();

  emailBtn.addEventListener("click", function () {
    var to = prompt("Send this link to which email address?");
    if (!to) return;
    var fd = new FormData(); fd.append("to", to);
    fetch("/api/shares/" + token + "/email", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
      .then(function (res) {
        if (res.status === 200 && res.d.ok) { window.BS.toast("Email sent to " + to); }
        else { window.location.href = window.BS.mailtoLink(url); }
      })
      .catch(function () { window.location.href = window.BS.mailtoLink(url); });
  });
})();
