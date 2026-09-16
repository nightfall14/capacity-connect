(function () {
  document.querySelectorAll(".file-preview-trigger").forEach(function (button) {
    button.addEventListener("click", function () {
      openFilePreview(button.dataset.fileUrl, button.dataset.fileType, button.dataset.fileTitle);
    });
  });
  document.getElementById("file-preview-close")?.addEventListener("click", closeFilePreview);
  let editingItemId = null;
  let replacingItemId = null;
  const editModal = document.getElementById("module-item-edit-modal");
  const editForm = document.getElementById("module-item-edit-form");
  const replaceInput = document.getElementById("module-item-replace-input");

  document.querySelectorAll(".edit-module-item").forEach(function (button) {
    button.addEventListener("click", function () {
      editingItemId = button.dataset.itemId;
      document.getElementById("module-item-edit-title").value = button.dataset.title;
      document.getElementById("module-item-edit-url").value = button.dataset.contentUrl;
      editModal.classList.remove("hidden");
      editModal.classList.add("flex");
    });
  });
  document.getElementById("module-item-edit-cancel")?.addEventListener("click", closeItemEdit);
  editForm?.addEventListener("submit", async function (event) {
    event.preventDefault();
    try {
      const response = await fetch("/trainer/modules/items/" + editingItemId, {
        method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: document.getElementById("module-item-edit-title").value.trim(),
          content_url: document.getElementById("module-item-edit-url").value.trim()
        })
      });
      const result = await response.json();
      if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to update item.");
      window.location.reload();
    } catch (error) { showToast(error.message, true); }
  });
  document.querySelectorAll(".replace-module-item").forEach(function (button) {
    button.addEventListener("click", function () {
      replacingItemId = button.dataset.itemId;
      replaceInput.click();
    });
  });
  replaceInput?.addEventListener("change", async function () {
    if (!replaceInput.files.length || !replacingItemId) return;
    const formData = new FormData();
    formData.append("file", replaceInput.files[0]);
    try {
      const response = await fetch("/trainer/modules/items/" + replacingItemId + "/replace-file", {method: "POST", body: formData});
      const result = await response.json();
      if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to replace file.");
      window.location.reload();
    } catch (error) { showToast(error.message, true); }
    replaceInput.value = "";
  });
  document.querySelectorAll(".delete-module-item").forEach(function (button) {
    button.addEventListener("click", async function () {
      if (!window.confirm("Are you sure you want to delete this content item?")) return;
      try {
        const response = await fetch("/trainer/modules/items/" + button.dataset.itemId, {method: "DELETE"});
        const result = await response.json();
        if (!response.ok || result.status !== "success") throw new Error(result.message || "Unable to delete item.");
        document.getElementById("module-item-" + button.dataset.itemId)?.remove();
      } catch (error) { showToast(error.message, true); }
    });
  });
  function closeItemEdit() {
    editModal?.classList.add("hidden");
    editModal?.classList.remove("flex");
  }

  function openFilePreview(fileUrl, fileType, title) {
    const modal = document.getElementById("file-preview-modal");
    const iframe = document.getElementById("file-preview-iframe");
    if (!modal || !iframe) return;
    document.getElementById("file-preview-title").textContent = title;
    document.getElementById("file-download-btn").href = fileUrl;
    const absoluteUrl = new URL(fileUrl, window.location.origin).href;
    iframe.src = fileType === "pdf"
      ? absoluteUrl
      : "https://docs.google.com/gview?url=" + encodeURIComponent(absoluteUrl) + "&embedded=true";
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }

  function closeFilePreview() {
    const modal = document.getElementById("file-preview-modal");
    const iframe = document.getElementById("file-preview-iframe");
    if (!modal || !iframe) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    iframe.src = "";
  }

  const modal = document.getElementById("transcript-modal");
  const modalBody = document.getElementById("transcript-modal-body");
  const closeModal = document.getElementById("close-transcript-modal");
  const editButton = document.getElementById("transcript-edit-btn");
  const saveButton = document.getElementById("transcript-save-btn");
  let currentTranscriptModuleId = null;

  document.querySelectorAll(".preview-transcript").forEach(function (button) {
    button.addEventListener("click", async function () {
      modal.classList.remove("hidden");
      modal.classList.add("flex");
      modalBody.innerHTML = '<div class="flex items-center gap-2 text-gray-500"><span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent"></span>Loading...</div>';
      try {
        const response = await fetch(
          "/trainer/modules/" + encodeURIComponent(button.dataset.videoId) + "/transcript/preview"
        );
        const payload = await response.json();
        let segments = payload.data;
        if (typeof segments === "string") {
          segments = JSON.parse(segments);
        }
        if (!response.ok || payload.status !== "success") {
          throw new Error(payload.message || "No transcript found.");
        }
        if (!Array.isArray(segments) || segments.length === 0) {
          throw new Error("Transcript is empty.");
        }
        const groupedSegments = groupTranscriptSegments(segments, 4);
        modalBody.replaceChildren();
        modalBody.className = "space-y-4 overflow-y-auto p-6 font-mono text-sm";
        currentTranscriptModuleId = Number(button.dataset.videoId);
        editButton?.classList.remove("hidden");
        saveButton?.classList.add("hidden");
        groupedSegments.forEach(function (segment) {
          const row = document.createElement("div");
          row.className = "transcript-segment flex items-start gap-4 border-b border-gray-100 pb-2";
          row.dataset.start = segment.start;
          row.dataset.end = segment.end;
          const time = document.createElement("span");
          time.className = "w-32 shrink-0 font-bold text-blue-600";
          time.textContent = "[" + formatTime(segment.start) + " - " + formatTime(segment.end) + "]";
          const text = document.createElement("textarea");
          text.readOnly = true;
          text.rows = 3;
          text.className = "transcript-text w-full resize-none border-transparent bg-transparent p-2 text-gray-800 focus:outline-none";
          text.value = segment.text;
          row.append(time, text);
          modalBody.appendChild(row);
        });
      } catch (error) {
        modalBody.textContent = error.message;
        modalBody.className = "p-6 text-sm text-rose-600";
      }
    });
  });
  closeModal?.addEventListener("click", function () {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    modalBody.replaceChildren();
    modalBody.className = "space-y-4 overflow-y-auto p-6 font-mono text-sm";
  });

  editButton?.addEventListener("click", function () {
    editButton.classList.add("hidden");
    saveButton.classList.remove("hidden");
    modalBody.querySelectorAll(".transcript-text").forEach(function (textarea) {
      textarea.readOnly = false;
      textarea.className = "transcript-text w-full resize-none rounded border border-gray-300 bg-white p-2 text-gray-800 focus:ring-2 focus:ring-blue-500";
    });
  });

  saveButton?.addEventListener("click", async function () {
    if (!currentTranscriptModuleId) return;
    saveButton.disabled = true;
    saveButton.textContent = "Saving...";
    const segments = Array.from(modalBody.querySelectorAll(".transcript-segment")).map(function (row) {
      return {
        start: Number(row.dataset.start) || 0,
        end: Number(row.dataset.end) || 0,
        text: row.querySelector(".transcript-text").value.trim()
      };
    });
    try {
      const response = await fetch("/trainer/modules/" + encodeURIComponent(currentTranscriptModuleId) + "/transcript/edit", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({segments: segments})
      });
      const result = await response.json();
      if (!response.ok || result.status !== "success") {
        throw new Error(result.message || "Unable to save transcript.");
      }
      saveButton.textContent = "Saved";
      setTimeout(function () {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        saveButton.disabled = false;
        saveButton.textContent = "Save Changes";
      }, 700);
    } catch (error) {
      saveButton.disabled = false;
      saveButton.textContent = "Save Changes";
      showToast(error.message, true);
    }
  });

  function formatTime(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    return String(Math.floor(value / 60)).padStart(2, "0") + ":" +
      String(value % 60).padStart(2, "0");
  }

  function groupTranscriptSegments(segments, groupSize = 4) {
    if (!Array.isArray(segments) || segments.length === 0) return [];
    const grouped = [];
    for (let i = 0; i < segments.length; i += groupSize) {
      const chunk = segments.slice(i, i + groupSize);
      grouped.push({
        start: chunk[0].start,
        end: chunk[chunk.length - 1].end,
        text: chunk.map(function (segment) {
          return String(segment.text || "").trim();
        }).join(" ")
      });
    }
    return grouped;
  }

  const bar = document.getElementById("course-publish-bar");
  const button = document.getElementById("btn-publish-course");
  if (!bar || !button || button.disabled) return;

  button.addEventListener("click", async function () {
    button.disabled = true;
    button.textContent = "Publishing...";
    try {
      const response = await fetch(
        "/trainer/courses/" + bar.dataset.courseId + "/publish-changes",
        { method: "POST", headers: { "Accept": "application/json" } }
      );
      const data = await response.json();
      if (!response.ok || data.status !== "success") {
        throw new Error(data.error || "Unable to publish course changes.");
      }
      const status = document.getElementById("course-publish-status");
      status.textContent = "All Changes Live";
      status.className = "rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-800";
      bar.className = bar.className.replace("border-amber-200 bg-amber-50", "border-emerald-200 bg-emerald-50");
      document.getElementById("draft-banner")?.remove();
      document.querySelectorAll(".publication-badge").forEach(function (badge) {
        badge.textContent = "Live for Trainees";
        badge.className = "publication-badge rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-700";
      });
      button.textContent = "Course Live";
      button.className = "flex cursor-not-allowed items-center gap-2 rounded-lg bg-slate-400 px-5 py-2.5 font-medium text-white shadow";
      showToast(data.message);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Update Course & Make Live";
      showToast(error.message, true);
    }
  });

  function showToast(message, error) {
    const toast = document.createElement("div");
    toast.className = "fixed bottom-6 right-6 z-50 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg " +
      (error ? "bg-rose-600" : "bg-emerald-600");
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
  }
})();
