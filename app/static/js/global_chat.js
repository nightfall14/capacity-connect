(function () {
  "use strict";

  const drawer = document.getElementById("global-chat-drawer");
  if (!drawer) return;

  const openButton = document.getElementById("global-chat-open");
  const closeButton = document.getElementById("global-chat-close");
  const backdrop = document.getElementById("global-chat-backdrop");
  const messages = document.getElementById("global-chat-messages");
  const form = document.getElementById("global-chat-form");
  const input = document.getElementById("global-chat-input");
  const anonymousToggle = document.getElementById("global-chat-anonymous");
  const status = document.getElementById("global-chat-status");
  const onlineCount = document.getElementById("online-count");
  const currentUser = window.capacityConnectUser || {};
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(wsProtocol + "://" + window.location.host + "/ws/chat");
  let pendingRescueRequesterId = null;

  function showToast(message, error) {
    const toast = document.createElement("div");
    toast.className = "fixed bottom-6 right-6 z-[80] rounded-lg px-4 py-3 text-sm font-medium text-white shadow-lg " +
      (error ? "bg-rose-600" : "bg-emerald-600");
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 4500);
  }

  window.requestPeerRescue = function (courseId) {
    if (ws.readyState !== WebSocket.OPEN) {
      showToast("Community connection is not ready.", true);
      return;
    }
    ws.send(JSON.stringify({type: "peer_rescue_request", course_id: Number(courseId)}));
  };

  window.closePeerRescue = function () {
    document.getElementById("peer-rescue-modal")?.classList.add("hidden");
    document.getElementById("peer-rescue-modal")?.classList.remove("flex");
    pendingRescueRequesterId = null;
  };

  window.acceptPeerRescue = function () {
    if (pendingRescueRequesterId && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: "peer_rescue_accept", requester_id: pendingRescueRequesterId}));
    }
    window.closePeerRescue();
    showToast("Peer Rescue accepted.");
  };

  window.updatePresence = function (onlineUserIds) {
    const online = new Set((onlineUserIds || []).map(Number));
    document.querySelectorAll(".presence-dot").forEach(function (dot) {
      dot.classList.toggle("hidden", !online.has(Number(dot.dataset.userId)));
    });
  };

  function setOpen(isOpen) {
    drawer.classList.toggle("translate-x-full", !isOpen);
    backdrop.classList.toggle("hidden", !isOpen);
    drawer.setAttribute("aria-hidden", String(!isOpen));
    openButton.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) input.focus();
  }

  function appendMessage(data) {
    const mine = Number(data.user_id) === Number(currentUser.id) && !data.is_anonymous;
    const row = document.createElement("div");
    row.className = "flex " + (mine ? "justify-end" : "justify-start");
    const bubble = document.createElement("div");
    bubble.className = "max-w-[85%] rounded-xl px-4 py-3 text-sm shadow-sm " +
      (mine ? "bg-blue-600 text-white" : "bg-white text-slate-800 border border-slate-200");
    const meta = document.createElement("div");
    meta.className = "mb-1 text-xs font-semibold " + (mine ? "text-blue-100" : "text-slate-500");
    meta.textContent = data.user + " [" + data.role + "] · " + data.timestamp;
    const body = document.createElement("div");
    body.className = "break-words";
    body.textContent = data.message;
    bubble.append(meta, body);
    row.appendChild(bubble);
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  ws.addEventListener("open", function () {
    status.textContent = "Connected";
    ws.send(JSON.stringify({ type: "join_global" }));
  });
  ws.addEventListener("close", function () { status.textContent = "Offline"; });
  ws.addEventListener("error", function () { status.textContent = "Connection error"; });
  ws.addEventListener("message", function (event) {
    const data = JSON.parse(event.data);
    if (data.type === "online_count") {
      onlineCount.textContent = "Online: " + data.count;
    } else if (data.type === "online_users_update") {
      onlineCount.textContent = "Online: " + (data.online_users || []).length;
      window.updatePresence(data.online_users || []);
    } else if (data.type === "incoming_peer_rescue") {
      pendingRescueRequesterId = Number(data.requester_id);
      document.getElementById("rescue-requester-name").textContent = data.requester_name || "A trainee";
      document.getElementById("rescue-course-name").textContent = data.course_name || "this course";
      const rescueModal = document.getElementById("peer-rescue-modal");
      rescueModal?.classList.remove("hidden");
      rescueModal?.classList.add("flex");
    } else if (data.type === "peer_rescue_failed") {
      showToast(data.message || "No available peers online.", true);
    } else if (data.type === "peer_rescue_pending") {
      showToast(data.message || "Request sent to an available peer.");
    } else if (data.type === "peer_rescue_accepted") {
      showToast(data.message || "A peer accepted your request.");
    } else if (data.type === "message") {
      appendMessage(data);
    } else if (data.type === "history") {
      messages.innerHTML = "";
      (data.data.messages || []).forEach(function (message) {
        appendMessage({
          user: message.user || message.sender_name || "Community member",
          role: message.role || "Member",
          message: message.message || message.body || "",
          timestamp: new Date(message.created_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}),
          user_id: message.sender_id,
          is_anonymous: message.anonymous
        });
      });
    }
  });

  openButton.addEventListener("click", function () { setOpen(true); });
  closeButton.addEventListener("click", function () { setOpen(false); });
  backdrop.addEventListener("click", function () { setOpen(false); });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      message: text,
      is_anonymous: anonymousToggle.checked
    }));
    input.value = "";
  });
})();
