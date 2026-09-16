(function () {
  "use strict";

  const video = document.getElementById("lecture-video");
  if (!video) return;

  const userId = Number(video.dataset.userId || 0);
  const courseId = Number(video.dataset.courseId || 0);
  const videoId = Number(video.dataset.videoId || 1);
  const telemetryUrl = video.dataset.telemetryUrl || "/api/telemetry";
  const fallbackUrl = video.dataset.fallbackUrl;
  let seekingFrom = 0;
  let lastTime = 0;
  let lastCheckpoint = -1;
  const checkpointPercentages = (video.dataset.checkpoints || "25,50,75,100").split(",")
    .map(Number).filter(Number.isFinite);
  let checkpointTimes = [];

  function resolveCheckpoints() {
    const duration = Number(video.duration);
    if (!Number.isFinite(duration) || duration <= 0) return;
    checkpointTimes = checkpointPercentages
      .filter(function (percentage) { return percentage > 0 && percentage <= 100; })
      .map(function (percentage) { return duration * percentage / 100; });
  }
  video.addEventListener("loadedmetadata", resolveCheckpoints);
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) resolveCheckpoints();

  video.addEventListener("error", function () {
    if (!fallbackUrl || video.dataset.fallbackLoaded === "true") return;
    video.dataset.fallbackLoaded = "true";
    video.src = fallbackUrl;
    video.load();
  });

  function send(eventType, timestamp) {
    if (!userId || !courseId || !Number.isFinite(timestamp)) return;
    fetch(telemetryUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      credentials: "same-origin",
      body: JSON.stringify({
        video_id: videoId, user_id: userId, course_id: courseId,
        event_type: eventType, video_timestamp: timestamp
      })
    }).catch(function () { /* telemetry must not interrupt playback */ });
  }

  video.addEventListener("pause", function () {
    if (!video.ended) send("PAUSE", video.currentTime);
  });
  video.addEventListener("seeking", function () { seekingFrom = lastTime; });
  video.addEventListener("seeked", function () {
    const delta = video.currentTime - seekingFrom;
    if (Math.abs(delta) < 0.5) return;
    send(delta < 0 ? "REWIND" : "SEEK", video.currentTime);
  });
  video.addEventListener("timeupdate", function () {
    const checkpoint = checkpointTimes.findIndex(function (time) {
      return time >= 0 && video.currentTime >= time && time > lastCheckpoint;
    });
    if (checkpoint < 0) return;
    lastCheckpoint = checkpointTimes[checkpoint];
    video.pause();
    const modal = document.getElementById("checkpoint-modal");
    if (modal) modal.classList.remove("d-none");
    lastTime = video.currentTime;
  });
  video.addEventListener("timeupdate", function () { lastTime = video.currentTime; });

  window.capacityConnect = {
    jumpTo: function (seconds) {
      video.currentTime = Number(seconds);
      video.play().catch(function () {});
    },
    submitCheckpoint: function () {
      const answer = document.querySelector("input[name='checkpoint-answer']:checked");
      const feedback = document.getElementById("checkpoint-feedback");
      if (!answer) { if (feedback) feedback.textContent = "Choose an answer."; return; }
      if (feedback) feedback.textContent = answer.value === "loop" ? "Correct." : "Review the understanding loop.";
      if (answer.value === "loop") {
        document.getElementById("checkpoint-modal").classList.add("d-none");
        video.play().catch(function () {});
      }
    }
  };
})();
