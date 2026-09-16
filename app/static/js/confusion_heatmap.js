(function () {
  "use strict";

  const strip = document.getElementById("confusion-heatmap-strip");
  const ticks = document.getElementById("confusion-heatmap-ticks");
  const video = document.getElementById("trainer-lecture-video");
  if (!strip || !video) return;
  const lectureId = Number(strip.dataset.lectureId);
  if (!Number.isInteger(lectureId) || lectureId <= 0) return;

  function loadHeatmap() {
    fetch("/api/lectures/" + encodeURIComponent(lectureId) + "/confusion-heatmap", {
    credentials: "same-origin"
  })
    .then(function (response) {
      if (!response.ok) throw new Error("Unable to load confusion heatmap.");
      return response.json();
    })
    .then(function (payload) {
      const duration = Number(payload.duration_seconds) || 0;
      const buckets = Array.isArray(payload.buckets) ? payload.buckets : [];
      if (!duration || !buckets.length) return;
      strip.replaceChildren();
      ticks.replaceChildren();
      buckets.forEach(function (bucket) {
        const segment = document.createElement("button");
        const start = Number(bucket.start_seconds) || 0;
        const end = Number(bucket.end_seconds) || start;
        segment.type = "button";
        segment.className = "h-full min-w-0 border-0 p-0 transition-opacity hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-white";
        segment.style.width = Math.max(0, ((end - start) / duration) * 100) + "%";
        const details = bucketDetails(bucket);
        segment.style.backgroundColor = details.color;
        segment.title = "Time: " + formatTime(start) + "–" + formatTime(end) +
          "\nInteractions: " + details.interactions +
          "\nPauses: " + details.pauses +
          "\nRewinds: " + details.rewinds +
          "\nStruggle level: " + details.level;
        segment.addEventListener("click", function () {
          video.currentTime = start;
          video.play().catch(function () {});
        });
        strip.appendChild(segment);
      });
      renderTicks(duration);
    })
    .catch(function () { strip.hidden = true; });
  }
  loadHeatmap();

  window.addEventListener("lecture-duration-resolved", function (event) {
    if (Number(event.detail && event.detail.lectureId) === lectureId) {
      strip.hidden = false;
      loadHeatmap();
    }
  });

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    return String(Math.floor(total / 60)).padStart(2, "0") + ":" +
      String(total % 60).padStart(2, "0");
  }

  function bucketDetails(bucket) {
    const pauses = Number(bucket.pause_count) || 0;
    const rewinds = Number(bucket.rewind_count) || 0;
    const interactions = pauses + rewinds;
    const weightedScore = Number(bucket.raw_score) || 0;
    if (interactions === 0) {
      return {pauses: pauses, rewinds: rewinds, interactions: 0, level: "Unseen", color: "#E2E8F0"};
    }
    if (weightedScore <= 2) {
      return {pauses: pauses, rewinds: rewinds, interactions: interactions, level: "Minor Pause", color: "#FACC15"};
    }
    if (weightedScore <= 5) {
      return {pauses: pauses, rewinds: rewinds, interactions: interactions, level: "Moderate Repeat", color: "#FB923C"};
    }
    return {pauses: pauses, rewinds: rewinds, interactions: interactions, level: "Critical Struggle", color: "#EF4444"};
  }

  function renderTicks(duration) {
    const interval = tickInterval(duration);
    for (let time = 0; time <= duration; time += interval) appendTick(time, duration);
    if (duration % interval !== 0) appendTick(duration, duration);
  }

  function tickInterval(duration) {
    const candidates = [15, 30, 60, 120, 300, 600, 900, 1800];
    const target = duration / 12;
    return candidates.reduce(function (best, candidate) {
      return Math.abs(candidate - target) < Math.abs(best - target) ? candidate : best;
    }, candidates[0]);
  }

  function appendTick(time, duration) {
    const label = document.createElement("span");
    label.className = "absolute whitespace-nowrap";
    label.style.left = (time / duration * 100) + "%";
    if (time === 0) label.classList.add("translate-x-0");
    else if (time === duration) label.classList.add("-translate-x-full");
    else label.classList.add("-translate-x-1/2");
    label.textContent = formatTime(time);
    ticks.appendChild(label);
  }
})();
