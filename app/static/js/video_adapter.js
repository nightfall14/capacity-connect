(function () {
  "use strict";

  const url = window.courseVideoUrl || "";
  const userId = Number(window.currentUserId);
  const courseId = Number(window.currentCourseId);
  const videoId = Number(window.currentVideoId);
  const transcript = Array.isArray(window.transcriptSegments) ? window.transcriptSegments : [];
  let player = null;
  let lastTime = 0;
  let heartbeat = null;

  function youtubeId(value) {
    try {
      const parsed = new URL(value);
      if (parsed.hostname === "youtu.be") return parsed.pathname.slice(1);
      if (parsed.hostname.endsWith("youtube.com")) {
        if (parsed.pathname === "/watch") return parsed.searchParams.get("v");
        const parts = parsed.pathname.split("/");
        if (["embed", "shorts"].includes(parts[1])) return parts[2];
      }
    } catch (_) { return null; }
    return null;
  }

  function send(eventType, timestamp, duration) {
    if (!userId || !courseId || !Number.isFinite(timestamp)) return;
    fetch("/api/telemetry", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        user_id: userId, course_id: courseId, event_type: eventType,
        video_timestamp: timestamp, duration: duration || 0,
        video_id: videoId || null
      })
    }).catch(function () {});
  }

  function highlight(time) {
    document.querySelectorAll("[data-transcript-start]").forEach(function (item) {
      const start = Number(item.dataset.transcriptStart);
      const end = Number(item.dataset.transcriptEnd);
      item.classList.toggle("bg-blue-50", time >= start && time <= end);
      item.classList.toggle("border-blue-500", time >= start && time <= end);
    });
  }

  function tick(getTime, getDuration, isPlaying) {
    const now = Number(getTime());
    const duration = Number(getDuration());
    if (!Number.isFinite(now)) return;
    if (Math.abs(now - lastTime) > 2 && lastTime > 0) send("MEDIA_SEEK", now, duration);
    lastTime = now;
    highlight(now);
    if (isPlaying()) send("MEDIA_HEARTBEAT", now, duration);
  }

  function startHeartbeat(getTime, getDuration, isPlaying) {
    window.clearInterval(heartbeat);
    heartbeat = window.setInterval(function () {
      if (isPlaying()) send("MEDIA_HEARTBEAT", Number(getTime()), Number(getDuration()));
    }, 10000);
  }

  function nativePlayer() {
    const video = document.getElementById("lecture-video");
    if (!video) return;
    video.addEventListener("play", function () { send("MEDIA_PLAY", video.currentTime, video.duration); startHeartbeat(() => video.currentTime, () => video.duration, () => !video.paused); });
    video.addEventListener("pause", function () { send("MEDIA_PAUSE", video.currentTime, video.duration); window.clearInterval(heartbeat); });
    video.addEventListener("seeked", function () { send("MEDIA_SEEK", video.currentTime, video.duration); });
    window.setInterval(function () { tick(() => video.currentTime, () => video.duration, () => !video.paused); }, 500);
  }

  function youtubePlayer() {
    const video = document.getElementById("lecture-video");
    if (video) video.outerHTML = '<div id="youtube-player" class="h-full w-full"></div>';
    const id = youtubeId(url);
    if (!id) return nativePlayer();
    window.onYouTubeIframeAPIReady = function () {
      player = new YT.Player("youtube-player", {
        videoId: id,
        playerVars: { rel: 0, modestbranding: 1 },
        events: {
          onReady: function () {
            window.capacityConnectPublishVideoDuration?.(player.getDuration());
          },
          onStateChange: function (event) {
            if (event.data === YT.PlayerState.PLAYING) {
              send("MEDIA_PLAY", player.getCurrentTime(), player.getDuration());
              startHeartbeat(() => player.getCurrentTime(), () => player.getDuration(), () => player.getPlayerState() === YT.PlayerState.PLAYING);
            } else if (event.data === YT.PlayerState.PAUSED) {
              send("MEDIA_PAUSE", player.getCurrentTime(), player.getDuration());
              window.clearInterval(heartbeat);
            }
          }
        }
      });
      window.youtubePlayer = player;
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(script);
    window.setInterval(function () {
      if (player && player.getPlayerState) tick(() => player.getCurrentTime(), () => player.getDuration(), () => player.getPlayerState() === YT.PlayerState.PLAYING);
    }, 500);
  }

  const transcriptTarget = document.getElementById("transcript-segments");
  if (transcriptTarget && !transcriptTarget.querySelector("[data-transcript-start]")) {
    transcript.forEach(function (segment) {
      const item = document.createElement("button");
      item.type = "button";
      item.dataset.transcriptStart = segment.start;
      item.dataset.transcriptEnd = segment.end;
      item.className = "block w-full border-l-4 border-transparent p-3 text-left text-sm text-slate-600 transition hover:bg-blue-50";
      item.textContent = segment.text;
      item.addEventListener("click", function () { window.seekToTimestamp(Number(segment.start)); });
      const empty = transcriptTarget.querySelector("[data-transcript-empty]");
      if (empty) empty.remove();
      transcriptTarget.appendChild(item);
    });
  }

  window.seekToTimestamp = function (seconds) {
    if (player) { player.seekTo(seconds, true); player.playVideo(); return; }
    const video = document.getElementById("lecture-video");
    if (video) { video.currentTime = seconds; video.play().catch(function () {}); }
  };

  if (youtubeId(url)) youtubePlayer(); else nativePlayer();
})();
