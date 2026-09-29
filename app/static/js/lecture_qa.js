(function () {
  "use strict";

  const form = document.getElementById("lecture-qa-form");
  const result = document.getElementById("lecture-qa-result");
  const video = document.getElementById("lecture-video");
  const lectureId = Number(window.currentVideoId);
  if (!form || !result || !Number.isInteger(lectureId) || lectureId <= 0) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const input = form.querySelector("[name=question]");
    const question = String(input.value || "").trim();
    if (!question) return;
    result.textContent = "Searching transcript…";
    fetch("/api/lectures/" + encodeURIComponent(lectureId) + "/qa", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: question})
    })
      .then(function (response) { return response.ok ? response.json() : Promise.reject(); })
      .then(function (answer) {
        result.replaceChildren();
        if (!answer.matched) {
          result.textContent = answer.message || "No matching answer found in this lecture transcript.";
          return;
        }
        const text = document.createElement("p");
        text.className = "text-sm text-slate-700";
        text.textContent = answer.text;
        const timestamp = document.createElement("p");
        timestamp.className = "mt-2 text-xs font-semibold text-slate-500";
        timestamp.textContent = "Playing from " + formatTime(answer.start_seconds);
        result.append(text, timestamp);
        if (typeof window.seekToTimestamp === "function") {
          window.seekToTimestamp(Number(answer.start_seconds));
        } else if (video) {
          video.currentTime = Number(answer.start_seconds);
          video.play().catch(function () {});
        }
      })
      .catch(function () { result.textContent = "Unable to search this lecture transcript."; });
  });

  function formatTime(seconds) {
    const whole = Math.max(0, Math.floor(Number(seconds) || 0));
    return String(Math.floor(whole / 60)).padStart(2, "0") + ":" + String(whole % 60).padStart(2, "0");
  }
})();
