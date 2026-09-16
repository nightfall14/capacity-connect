(function () {
  const heatmapBar = document.getElementById("heatmap-bar");
  const timeline = document.getElementById("heatmap-timeline-scale");
  if (!heatmapBar || !timeline || !heatmapBar.dataset.videoId) return;

  const videoId = heatmapBar.dataset.videoId;
  const video = document.getElementById("lecture-video");
  let loadedBuckets = [];
  let apiDuration = 0;
  const colors = {
    unseen: "#E2E8F0",
    smooth: "#10B981",
    yellow: "#FACC15",
    orange: "#FB923C",
    red: "#EF4444"
  };
  const labels = {
    unseen: "Unseen",
    smooth: "Smooth",
    yellow: "Minor Pause",
    orange: "Moderate Repeat",
    red: "Critical Struggle"
  };

  function loadHeatmap() {
    fetch("/api/telemetry/heatmap/" + encodeURIComponent(videoId))
    .then(function (response) {
      if (!response.ok) throw new Error("Unable to load heatmap.");
      return response.json();
    })
    .then(function (payload) {
      loadedBuckets = Array.isArray(payload.buckets) ? payload.buckets : [];
      // Both API fields are expressed in seconds. Prefer the explicit field.
      apiDuration = Number(payload.total_duration_seconds ?? payload.total_duration) || 0;
      renderHeatmap(loadedBuckets, apiDuration);
    })
    .catch(function () {
      heatmapBar.replaceChildren();
      timeline.replaceChildren();
    });
  }
  loadHeatmap();

  window.addEventListener("lecture-duration-resolved", function (event) {
    if (Number(event.detail && event.detail.lectureId) === Number(videoId)) loadHeatmap();
  });

  function renderHeatmap(buckets, reportedDuration) {
    heatmapBar.replaceChildren();
    timeline.replaceChildren();

    // total_duration is always seconds. Do not derive it from a bucket label.
    const totalDurationSeconds = Math.floor(Number(reportedDuration) || 0);
    if (totalDurationSeconds <= 0) return;

    buckets.forEach(function (bucket) {
      const start = Math.max(0, Number(bucket.start_time) || 0);
      const end = Math.min(totalDurationSeconds, Number(bucket.end_time) || start);
      const bucketDuration = Math.max(0, end - start);
      if (bucketDuration === 0) return;

      const segment = document.createElement("button");
      segment.type = "button";
      segment.className = "h-full min-w-0 border-0 p-0";
      segment.style.width = (bucketDuration / totalDurationSeconds) * 100 + "%";
      segment.style.backgroundColor =
        bucket.color_hex || colors[bucket.status] || colors.unseen;
      segment.title =
        "Time: " + formatTime(start) + " - " + formatTime(end) +
        " | Status: " + (labels[bucket.status] || bucket.status) +
        " | Events: " + (bucket.count || 0);

      if (video) {
        segment.addEventListener("click", function () {
          video.currentTime = start;
          video.play().catch(function () {});
        });
      }
      heatmapBar.appendChild(segment);
    });

    // True mathematical ruler: one tick every 300 seconds (5 minutes).
    for (let t = 0; t <= totalDurationSeconds; t += 300) {
      appendTick(t, totalDurationSeconds, false);
    }

    // Add exactly one endpoint tick for videos not divisible by five minutes.
    if (totalDurationSeconds % 300 !== 0) {
      appendTick(totalDurationSeconds, totalDurationSeconds, true);
    }
  }

  function appendTick(time_in_seconds, total_duration, isEndpoint) {
    const pct = (time_in_seconds / total_duration) * 100;
    const tick = document.createElement("span");
    tick.className = "absolute text-[10px] text-gray-500";
    tick.classList.add(isEndpoint ? "-translate-x-full" : "-translate-x-1/2");
    tick.style.left = pct + "%";
    tick.textContent = formatTime(time_in_seconds);
    timeline.appendChild(tick);
  }

  function formatTime(seconds) {
    const totalSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(totalSeconds / 60);
    const secondsPart = totalSeconds % 60;
    return String(minutes).padStart(2, "0") + ":" +
      String(secondsPart).padStart(2, "0");
  }
})();
