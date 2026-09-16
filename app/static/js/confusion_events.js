(function () {
  "use strict";

  const video = document.getElementById("lecture-video");
  const lectureId = video && Number(video.dataset.videoId || window.currentVideoId);
  if (!video || !Number.isInteger(lectureId) || lectureId <= 0) return;

  let positionBeforeSeek = null;

  function record(eventType, timestamp) {
    if (!Number.isFinite(timestamp) || timestamp < 0) return;
    // Deliberately fire-and-forget: playback never waits on telemetry.
    fetch("/api/lectures/" + encodeURIComponent(lectureId) + "/video-events", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        event_type: eventType,
        video_timestamp_seconds: timestamp
      })
    }).catch(function () {});
  }

  video.addEventListener("pause", function () {
    if (!video.ended) record("pause", video.currentTime);
  });
  video.addEventListener("seeking", function () {
    if (positionBeforeSeek === null) positionBeforeSeek = video.currentTime;
  });
  video.addEventListener("seeked", function () {
    const newPosition = video.currentTime;
    if (positionBeforeSeek !== null && newPosition < positionBeforeSeek - 0.05) {
      record("rewind", newPosition);
    }
    positionBeforeSeek = null;
  });
})();
