(function () {
  "use strict";

  const video = document.querySelector("[data-lecture-duration-video]");
  if (!video) return;
  const lectureId = Number(video.dataset.videoId);
  if (!Number.isInteger(lectureId) || lectureId <= 0) return;

  let resolvedDuration = null;

  function publish(duration) {
    duration = Number(duration);
    if (!Number.isFinite(duration) || duration <= 0 || duration === resolvedDuration) return;
    resolvedDuration = duration;
    // This is a metadata cache, not an event payload. The server uses the
    // cached value to validate later interaction timestamps.
    fetch("/api/lectures/" + encodeURIComponent(lectureId) + "/duration", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({duration_seconds: duration})
    })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        const confirmedDuration = Number(payload && payload.duration_seconds);
        if (!Number.isFinite(confirmedDuration) || confirmedDuration <= 0) return;
        window.dispatchEvent(new CustomEvent("lecture-duration-resolved", {
          detail: {lectureId: lectureId, durationSeconds: confirmedDuration}
        }));
      })
      .catch(function () {});
  }

  video.addEventListener("loadedmetadata", function () { publish(video.duration); });
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) publish(video.duration);
  // The YouTube adapter calls this after its player reports real metadata.
  window.capacityConnectPublishVideoDuration = publish;
})();
