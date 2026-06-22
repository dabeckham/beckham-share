/* Workspace: authenticated upload, share modal, copy/email/expiry/revoke/delete. */
(function () {
  var dz = document.getElementById("dropzone");
  var input = document.getElementById("fileInput");
  var rows = document.getElementById("fileRows");
  var expirySelect = document.getElementById("expirySelect");
  var progress = dz.querySelector(".dz-progress");
  var bar = progress.querySelector(".bar > span");
  var pct = progress.querySelector(".pct");

  document.getElementById("uploadBtn").addEventListener("click", function () { input.click(); });
  dz.addEventListener("click", function () { if (progress.hidden) input.click(); });
  ["dragenter", "dragover"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("dragover"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("dragover"); });
  });
  dz.addEventListener("drop", function (e) { uploadAll(e.dataTransfer.files); });
  input.addEventListener("change", function () { uploadAll(input.files); input.value = ""; });

  function uploadAll(files) { Array.prototype.forEach.call(files, uploadOne); }

  function uploadOne(file) {
    progress.hidden = false; dz.querySelector(".dropzone-inner").hidden = true;
    var fp = window.BSFP ? window.BSFP.get() : { hash: "", components: null };
    var fd = new FormData();
    fd.append("file", file);
    fd.append("expiry_hours", expirySelect.value);
    fd.append("fp", fp.hash);
    fd.append("fp_data", JSON.stringify(fp.components));

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/files");
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        var p = Math.round((e.loaded / e.total) * 100);
        bar.style.width = p + "%"; pct.textContent = p + "%";
      }
    };
    xhr.onload = function () {
      progress.hidden = true; dz.querySelector(".dropzone-inner").hidden = false;
      bar.style.width = "0%"; pct.textContent = "0%";
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 200 && data.ok) { addRow(data); window.BS.toast("Uploaded " + data.filename); }
      else { window.BS.toast(data.error || "Upload failed"); }
    };
    xhr.onerror = function () { progress.hidden = true; window.BS.toast("Network error"); };
    xhr.send(fd);
  }

  function addRow(f) {
    var empty = document.getElementById("emptyState");
    if (empty) empty.remove();
    var tr = document.createElement("tr");
    tr.dataset.id = f.id; tr.dataset.token = f.token; tr.dataset.share = f.share_url; tr.dataset.name = f.filename;
    tr.innerHTML =
      '<td class="cell-name"><span class="file-ico"></span></td>' +
      '<td>' + f.size_h + '</td>' +
      '<td class="cell-exp">' + (f.expires_at ? f.expires_at.slice(0, 10) : "Never") + '</td>' +
      '<td>0</td>' +
      '<td class="cell-actions">' +
        '<button class="btn btn-ghost btn-sm act-share">Share</button>' +
        '<button class="btn btn-ghost btn-sm act-copy">Copy link</button>' +
        '<button class="btn btn-ghost btn-sm act-delete" title="Delete">&times;</button>' +
      '</td>';
    tr.querySelector(".cell-name").appendChild(document.createTextNode(f.filename));
    rows.prepend(tr);
  }

  // Row actions (delegated)
  rows.addEventListener("click", function (e) {
    var tr = e.target.closest("tr"); if (!tr) return;
    if (e.target.classList.contains("act-copy")) {
      window.BS.copyText(tr.dataset.share).then(function (ok) { window.BS.toast(ok ? "Link copied" : "Copy failed"); });
    } else if (e.target.classList.contains("act-share")) {
      openModal(tr);
    } else if (e.target.classList.contains("act-delete")) {
      if (!confirm("Delete \"" + tr.dataset.name + "\"? This removes the file and its link.")) return;
      fetch("/api/files/" + tr.dataset.id, { method: "DELETE" }).then(function (r) {
        if (r.ok) { tr.remove(); window.BS.toast("Deleted"); }
      });
    }
  });

  // Share modal
  var modal = document.getElementById("shareModal");
  var modalLink = document.getElementById("modalLink");
  var modalExpiry = document.getElementById("modalExpiry");
  var modalEmail = document.getElementById("modalEmail");
  var current = null;

  function openModal(tr) {
    current = tr;
    document.getElementById("modalFile").textContent = tr.dataset.name;
    modalLink.value = tr.dataset.share;
    modal.hidden = false;
  }
  function closeModal() { modal.hidden = true; current = null; }
  document.getElementById("modalClose").addEventListener("click", closeModal);
  modal.addEventListener("click", function (e) { if (e.target === modal) closeModal(); });

  modalExpiry.addEventListener("change", function () {
    if (!current) return;
    var fd = new FormData(); fd.append("expiry_hours", modalExpiry.value);
    fetch("/api/shares/" + current.dataset.token + "/expiry", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          current.querySelector(".cell-exp").textContent = d.expires_at ? d.expires_at.slice(0, 10) : "Never";
          window.BS.toast("Expiry updated");
        }
      });
  });

  document.getElementById("modalEmailBtn").addEventListener("click", function () {
    if (!current) return;
    var to = modalEmail.value.trim();
    if (!to) { window.BS.toast("Enter an email address"); return; }
    var fd = new FormData(); fd.append("to", to);
    fetch("/api/shares/" + current.dataset.token + "/email", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
      .then(function (res) {
        if (res.status === 200 && res.d.ok) { window.BS.toast("Email sent"); modalEmail.value = ""; }
        else { window.location.href = window.BS.mailtoLink(current.dataset.share, current.dataset.name); }
      })
      .catch(function () { window.location.href = window.BS.mailtoLink(current.dataset.share, current.dataset.name); });
  });

  document.getElementById("modalRevoke").addEventListener("click", function () {
    if (!current || !confirm("Revoke this link? It will stop working immediately.")) return;
    fetch("/api/shares/" + current.dataset.token + "/revoke", { method: "POST" }).then(function (r) {
      if (r.ok) { current.querySelector(".cell-exp").textContent = "Revoked"; window.BS.toast("Link revoked"); closeModal(); }
    });
  });
})();
