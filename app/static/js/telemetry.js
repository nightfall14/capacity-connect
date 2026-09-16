(function () {
  "use strict";

  const video = document.getElementById("lecture-video");
  if (!video) return;

  const userId = Number(window.currentUserId);
  const courseId = Number(window.currentCourseId);
  let heartbeatTimer = null;

  function sendTelemetry(eventType, timestamp) {
    if (!userId || !courseId || !Number.isFinite(timestamp)) return;
    fetch("/api/telemetry", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      credentials: "same-origin",
      body: JSON.stringify({
        user_id: userId,
        course_id: courseId,
        event_type: eventType,
        video_timestamp: timestamp
      })
    }).catch(function () {
      // Telemetry must never interrupt playback.
    });
  }

  function stopHeartbeat() {
    if (heartbeatTimer !== null) {
      window.clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  video.addEventListener("play", function () {
    sendTelemetry("PLAY", video.currentTime);
    stopHeartbeat();
    heartbeatTimer = window.setInterval(function () {
      if (!video.paused && !video.ended) sendTelemetry("HEARTBEAT", video.currentTime);
    }, 10000);
  });

  video.addEventListener("pause", function () {
    sendTelemetry("PAUSE", video.currentTime);
    stopHeartbeat();
  });

  video.addEventListener("seeked", function () {
    sendTelemetry("SEEK", video.currentTime);
  });

  video.addEventListener("ended", stopHeartbeat);
})();
