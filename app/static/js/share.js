/* Public share page: the Email button opens the visitor's own mail client.
   Server-side relay email is reserved for signed-in members (see the workspace),
   so the public page never sends through our mailbox. */
(function () {
  var emailBtn = document.getElementById("emailBtn");
  if (!emailBtn) return;
  var url = document.getElementById("shareLink").value;
  emailBtn.addEventListener("click", function () {
    window.location.href = window.BS.mailtoLink(url);
  });
})();
