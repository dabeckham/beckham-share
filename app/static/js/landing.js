/* Landing page: anonymous upload with progress and a ready-to-share link. */
(function () {
  var dz = document.getElementById("dropzone");
  var input = document.getElementById("fileInput");
  var inner = dz.querySelector(".dropzone-inner");
  var progress = dz.querySelector(".dz-progress");
  var bar = progress.querySelector(".bar > span");
  var pct = progress.querySelector(".pct");
  var result = document.getElementById("result");
  var errorEl = document.getElementById("error");

  function showError(msg) { errorEl.textContent = msg; errorEl.hidden = false; }
  function reset() {
    progress.hidden = true; inner.hidden = false; bar.style.width = "0%"; pct.textContent = "0%";
    result.hidden = true; errorEl.hidden = true; input.value = "";
  }

  dz.addEventListener("click", function () { if (progress.hidden) input.click(); });
  dz.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") input.click(); });
  ["dragenter", "dragover"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("dragover"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("dragover"); });
  });
  dz.addEventListener("drop", function (e) { if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]); });
  input.addEventListener("change", function () { if (input.files.length) upload(input.files[0]); });

  function upload(file) {
    errorEl.hidden = true;
    inner.hidden = true; progress.hidden = false;

    var fp = window.BSFP ? window.BSFP.get() : { hash: "", components: null };
    var fd = new FormData();
    fd.append("file", file);
    fd.append("fp", fp.hash);
    fd.append("fp_data", JSON.stringify(fp.components));

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/anon-upload");
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        var p = Math.round((e.loaded / e.total) * 100);
        bar.style.width = p + "%"; pct.textContent = p + "%";
      }
    };
    xhr.onload = function () {
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 200 && data.ok) { showResult(data); }
      else { reset(); showError(data.error || "Upload failed. Please try again."); }
    };
    xhr.onerror = function () { reset(); showError("Network error. Please try again."); };
    xhr.send(fd);
  }

  function showResult(data) {
    progress.hidden = true;
    document.getElementById("resultFile").textContent = data.filename;
    var link = document.getElementById("shareLink");
    link.value = data.share_url;
    var meta = document.getElementById("resultMeta");
    meta.textContent = data.expires_at
      ? "Link expires " + new Date(data.expires_at).toLocaleString()
      : "This link does not expire.";
    document.getElementById("emailBtn").onclick = function () {
      window.location.href = window.BS.mailtoLink(data.share_url, data.filename);
    };
    result.hidden = false;
  }

  document.getElementById("uploadAnother").addEventListener("click", reset);
})();
