// ============================================================================
// GitLab Wiki Chat — frontend logic (vanilla JS)
// ============================================================================

// --- DOM references ---------------------------------------------------------

const appEl = document.getElementById("app");
const messagesEl = document.getElementById("messages");
const welcomeTemplate = document.getElementById("welcome-template");
const chatAreaEl = document.getElementById("chat-area");

const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const newChatBtn = document.getElementById("new-chat-btn");

const syncBtn = document.getElementById("sync-btn");
const syncSpinner = document.getElementById("sync-spinner");
const syncLabel = document.getElementById("sync-label");

const statusPagesEl = document.getElementById("status-pages");
const statusSyncEl = document.getElementById("status-sync");
const statusErrorEl = document.getElementById("status-error");

const gitlabLink = document.getElementById("gitlab-link");
const gitlabLinkText = document.getElementById("gitlab-link-text");
const headerTitle = document.getElementById("header-title");
const logoutBtn = document.getElementById("logout-btn");

const sidebarOpenBtn = document.getElementById("sidebar-open");
const sidebarCloseBtn = document.getElementById("sidebar-close");
const sidebarOverlay = document.getElementById("sidebar-overlay");

// --- Constants -----------------------------------------------------------------

const TEXTAREA_MAX_HEIGHT_PX = 200;
const STATUS_REFRESH_INTERVAL_MS = 30000;
const SYNC_RESET_DELAY_MS = 2500;

// --- State -------------------------------------------------------------------

const conversationHistory = [];
let isStreaming = false;

// --- Markdown / syntax highlighting setup ------------------------------------

try {
  if (window.markedHighlight && window.hljs && window.marked) {
    marked.use(
      window.markedHighlight.markedHighlight({
        langPrefix: "hljs language-",
        highlight(code, lang) {
          const language = hljs.getLanguage(lang) ? lang : "plaintext";
          return hljs.highlight(code, { language }).value;
        },
      })
    );
  }
  if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
  }
} catch {
  // marked / highlight.js unavailable (CDN blocked): fall back to plain text.
}

function renderMarkdown(text) {
  if (window.marked) {
    try {
      return marked.parse(text || "");
    } catch {
      // ignore and fall back to raw HTML escaping
    }
  }
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

// --- Sidebar (mobile) ---------------------------------------------------------

function openSidebar() {
  appEl.classList.add("sidebar-visible");
}

function closeSidebar() {
  appEl.classList.remove("sidebar-visible");
}

sidebarOpenBtn.addEventListener("click", openSidebar);
sidebarCloseBtn.addEventListener("click", closeSidebar);
sidebarOverlay.addEventListener("click", closeSidebar);

// --- Messages rendering ---------------------------------------------------------

function scrollToBottom() {
  chatAreaEl.scrollTop = chatAreaEl.scrollHeight;
}

function showWelcomeScreen() {
  messagesEl.appendChild(welcomeTemplate.content.cloneNode(true));
}

function hideWelcome() {
  document.getElementById("welcome")?.remove();
}

function avatarTextForRole(role) {
  if (role === "user") return "🧑";
  if (role === "error") return "⚠️";
  return "🤖";
}

// Builds the shared "avatar + bubble column" layout for a message row,
// ordering the parts so user messages appear on the right.
function buildMessageRow(role, bubble) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = avatarTextForRole(role);

  const col = document.createElement("div");
  col.className = "bubble-col";
  col.appendChild(bubble);

  if (role === "user") {
    wrapper.append(col, avatar);
  } else {
    wrapper.append(avatar, col);
  }

  return wrapper;
}

function appendMessage(role, content) {
  hideWelcome();

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(content || "");
  } else {
    bubble.textContent = content;
  }

  messagesEl.appendChild(buildMessageRow(role, bubble));
  scrollToBottom();
  return bubble;
}

function appendTypingIndicator() {
  hideWelcome();

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

  const wrapper = buildMessageRow("assistant", bubble);
  wrapper.id = "typing-indicator";
  messagesEl.appendChild(wrapper);
  scrollToBottom();
}

function removeTypingIndicator() {
  document.getElementById("typing-indicator")?.remove();
}

// --- Composer -------------------------------------------------------------------

function autoResizeTextarea() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
}

function updateSendButtonState() {
  sendBtn.disabled = isStreaming || inputEl.value.trim().length === 0;
}

inputEl.addEventListener("input", () => {
  autoResizeTextarea();
  updateSendButtonState();
});

inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", sendMessage);

// --- New conversation -------------------------------------------------------------

newChatBtn.addEventListener("click", () => {
  if (isStreaming) return;

  conversationHistory.length = 0;
  messagesEl.innerHTML = "";
  showWelcomeScreen();

  inputEl.value = "";
  autoResizeTextarea();
  updateSendButtonState();
  inputEl.focus();
});

// --- Chat / streaming ---------------------------------------------------------------

async function sendMessage() {
  const message = inputEl.value.trim();
  if (!message || isStreaming) return;

  appendMessage("user", message);
  inputEl.value = "";
  autoResizeTextarea();

  isStreaming = true;
  updateSendButtonState();
  appendTypingIndicator();

  let assistantBubble = null;
  let assistantText = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: conversationHistory }),
    });

    if (!response.ok || !response.body) {
      removeTypingIndicator();
      let detail = "";
      try {
        const errBody = await response.json();
        detail = errBody.error || errBody.detail || "";
      } catch {
        // no usable JSON body
      }
      appendMessage("error", detail || `Server error (${response.status}).`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // last incomplete fragment

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6);

        if (payload === "[DONE]") continue;

        let data;
        try {
          data = JSON.parse(payload);
        } catch {
          continue;
        }

        if (data.error) {
          removeTypingIndicator();
          appendMessage("error", data.error);
          continue;
        }

        if (data.delta) {
          if (!assistantBubble) {
            removeTypingIndicator();
            assistantBubble = appendMessage("assistant", "");
          }
          assistantText += data.delta;
          assistantBubble.innerHTML = renderMarkdown(assistantText) + '<span class="cursor"></span>';
          scrollToBottom();
        }
      }
    }

    removeTypingIndicator();

    if (assistantBubble) {
      // Remove the streaming cursor once the response is complete
      assistantBubble.innerHTML = renderMarkdown(assistantText);
    }

    if (assistantText) {
      conversationHistory.push({ role: "user", content: message });
      conversationHistory.push({ role: "assistant", content: assistantText });
    }
  } catch (err) {
    removeTypingIndicator();
    appendMessage("error", `Connection error: ${err.message}`);
  } finally {
    isStreaming = false;
    updateSendButtonState();
    inputEl.focus();
  }
}

// --- Status & sync ---------------------------------------------------------------

function formatRelativeTime(isoString) {
  if (!isoString) return "never";

  const date = new Date(isoString);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.round(diffMs / 60000);

  if (diffMin < 1) return "just now";
  if (diffMin === 1) return "1 min ago";
  if (diffMin < 60) return `${diffMin} min ago`;

  const diffHours = Math.round(diffMin / 60);
  if (diffHours === 1) return "1 hour ago";
  if (diffHours < 24) return `${diffHours} hours ago`;

  const diffDays = Math.round(diffHours / 24);
  return diffDays === 1 ? "1 day ago" : `${diffDays} days ago`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();

    statusPagesEl.textContent = `${data.pages_indexed ?? 0}`;
    statusSyncEl.textContent = data.is_syncing ? "syncing..." : formatRelativeTime(data.last_sync_at);

    if (data.last_sync_errors && data.last_sync_errors.length > 0) {
      statusErrorEl.hidden = false;
      statusErrorEl.textContent = `${data.last_sync_errors.length} error(s) during the last sync.`;
    } else {
      statusErrorEl.hidden = true;
      statusErrorEl.textContent = "";
    }

    logoutBtn.hidden = !data.auth_enabled;
  } catch {
    statusPagesEl.textContent = "—";
    statusSyncEl.textContent = "unavailable";
  }
}

async function triggerSync() {
  syncBtn.disabled = true;
  syncBtn.classList.remove("success", "error");
  syncSpinner.hidden = false;
  syncLabel.textContent = "Syncing...";

  try {
    const response = await fetch("/api/sync", { method: "POST" });
    const data = await response.json();

    if (!response.ok) {
      syncBtn.classList.add("error");
      syncLabel.textContent = data.error || "Sync failed";
    } else {
      syncBtn.classList.add("success");
      syncLabel.textContent = `${data.pages_indexed ?? 0} page(s) synced`;
    }
  } catch {
    syncBtn.classList.add("error");
    syncLabel.textContent = "Connection error";
  }

  syncSpinner.hidden = true;
  await refreshStatus();

  setTimeout(() => {
    syncBtn.classList.remove("success", "error");
    syncLabel.textContent = "Sync wikis";
    syncBtn.disabled = false;
  }, SYNC_RESET_DELAY_MS);
}

syncBtn.addEventListener("click", triggerSync);

logoutBtn.addEventListener("click", async () => {
  try {
    await fetch("/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
});

// --- App config (GitLab instance, title) ------------------------------------------

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return;

    const data = await response.json();

    if (data.gitlab_url) {
      gitlabLink.href = data.gitlab_url;
      gitlabLinkText.textContent = data.gitlab_url.replace(/^https?:\/\//, "");
      gitlabLink.hidden = false;
    }

    if (data.title) {
      headerTitle.textContent = data.title;
    }
  } catch {
    // /api/config unavailable: keep the default values without blocking the UI.
  }
}

// --- Init ---------------------------------------------------------------------------

showWelcomeScreen();
updateSendButtonState();
loadConfig();
refreshStatus();
setInterval(refreshStatus, STATUS_REFRESH_INTERVAL_MS);
