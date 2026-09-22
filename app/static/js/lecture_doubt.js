(function () {
  "use strict";

  const form = document.getElementById("lecture-doubt-form");
  const result = document.getElementById("lecture-doubt-result");
  const video = document.getElementById("lecture-video");
  const lectureId = Number(window.currentVideoId);
  if (!form || !result || !Number.isInteger(lectureId) || lectureId <= 0) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const input = form.querySelector("[name=question]");
    const question = String(input.value || "").trim();
    if (!question) return;
    const anonymous = Boolean(form.querySelector("[name=anonymous]")?.checked);
    result.textContent = "Posting your doubt…";
    fetch("/api/lecture/" + encodeURIComponent(lectureId) + "/ask", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        question: question,
        anonymous: anonymous,
        timestamp: Number(video?.currentTime || 0)
      })
    })
      .then(function (response) { return response.ok ? response.json() : Promise.reject(); })
      .then(function (answer) {
        input.value = "";
        result.textContent = answer.answer || "Your doubt has been posted for review.";
      })
      .catch(function () { result.textContent = "Unable to post this doubt. Please try again."; });
  });
})();
