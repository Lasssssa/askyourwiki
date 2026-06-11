// ============================================================================
// GitLab Wiki Chat — frontend logic (vanilla JS)
// ============================================================================

// --- DOM references ---------------------------------------------------------

const appEl = document.getElementById("app");
const messagesEl = document.getElementById("messages");
const welcomeEl = document.getElementById("welcome");
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

const sidebarOpenBtn = document.getElementById("sidebar-open");
const sidebarCloseBtn = document.getElementById("sidebar-close");
const sidebarOverlay = document.getElementById("sidebar-overlay");

// --- State -------------------------------------------------------------------

const history = [];
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
  // marked / highlight.js indisponibles (CDN bloqué) : on retombera sur du texte brut.
}

function renderMarkdown(text) {
  if (window.marked) {
    try {
      return marked.parse(text || "");
    } catch {
      // ignore et retombe sur l'échappement HTML brut
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

function hideWelcome() {
  if (welcomeEl) welcomeEl.remove();
}

function appendMessage(role, content) {
  hideWelcome();

  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "🧑" : role === "error" ? "⚠️" : "🤖";

  const col = document.createElement("div");
  col.className = "bubble-col";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(content || "");
  } else {
    bubble.textContent = content;
  }

  col.appendChild(bubble);

  if (role === "user") {
    wrapper.appendChild(col);
    wrapper.appendChild(avatar);
  } else {
    wrapper.appendChild(avatar);
    wrapper.appendChild(col);
  }

  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return bubble;
}

function appendTypingIndicator() {
  hideWelcome();

  const wrapper = document.createElement("div");
  wrapper.className = "message assistant";
  wrapper.id = "typing-indicator";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "🤖";

  const col = document.createElement("div");
  col.className = "bubble-col";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

  col.appendChild(bubble);
  wrapper.appendChild(avatar);
  wrapper.appendChild(col);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

// --- Composer -------------------------------------------------------------------

function autoResizeTextarea() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 200)}px`;
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

  history.length = 0;
  messagesEl.innerHTML = "";

  const fresh = document.createElement("div");
  fresh.className = "welcome";
  fresh.id = "welcome";
  fresh.innerHTML = `
    <div class="welcome-logo">📚</div>
    <h2>Posez une question sur vos wikis</h2>
    <p>Les réponses sont générées à partir du contenu des wikis GitLab indexés.</p>
  `;
  messagesEl.appendChild(fresh);

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
      body: JSON.stringify({ message, history }),
    });

    if (!response.ok || !response.body) {
      removeTypingIndicator();
      let detail = "";
      try {
        const errBody = await response.json();
        detail = errBody.error || errBody.detail || "";
      } catch {
        // pas de corps JSON exploitable
      }
      appendMessage("error", detail || `Erreur serveur (${response.status}).`);
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
      buffer = lines.pop(); // dernier fragment incomplet

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
      // Retire le curseur de streaming une fois la réponse terminée
      assistantBubble.innerHTML = renderMarkdown(assistantText);
    }

    if (assistantText) {
      history.push({ role: "user", content: message });
      history.push({ role: "assistant", content: assistantText });
    }
  } catch (err) {
    removeTypingIndicator();
    appendMessage("error", `Erreur de connexion : ${err.message}`);
  } finally {
    isStreaming = false;
    updateSendButtonState();
    inputEl.focus();
  }
}

// --- Status & sync ---------------------------------------------------------------

function formatRelativeTime(isoString) {
  if (!isoString) return "jamais";

  const date = new Date(isoString);
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.round(diffMs / 60000);

  if (diffMin < 1) return "à l'instant";
  if (diffMin === 1) return "il y a 1 min";
  if (diffMin < 60) return `il y a ${diffMin} min`;

  const diffHours = Math.round(diffMin / 60);
  if (diffHours === 1) return "il y a 1 h";
  if (diffHours < 24) return `il y a ${diffHours} h`;

  const diffDays = Math.round(diffHours / 24);
  return diffDays === 1 ? "il y a 1 jour" : `il y a ${diffDays} jours`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();

    statusPagesEl.textContent = `${data.pages_indexed ?? 0}`;
    statusSyncEl.textContent = data.is_syncing ? "en cours..." : formatRelativeTime(data.last_sync_at);

    if (data.last_sync_errors && data.last_sync_errors.length > 0) {
      statusErrorEl.hidden = false;
      statusErrorEl.textContent = `${data.last_sync_errors.length} erreur(s) lors de la dernière synchro.`;
    } else {
      statusErrorEl.hidden = true;
      statusErrorEl.textContent = "";
    }
  } catch {
    statusPagesEl.textContent = "—";
    statusSyncEl.textContent = "indisponible";
  }
}

async function triggerSync() {
  syncBtn.disabled = true;
  syncBtn.classList.remove("success", "error");
  syncSpinner.hidden = false;
  syncLabel.textContent = "Synchronisation...";

  try {
    const response = await fetch("/api/sync", { method: "POST" });
    const data = await response.json();

    if (!response.ok) {
      syncBtn.classList.add("error");
      syncLabel.textContent = data.error || "Échec de la synchronisation";
    } else {
      syncBtn.classList.add("success");
      syncLabel.textContent = `${data.pages_indexed ?? 0} page(s) synchronisée(s)`;
    }
  } catch {
    syncBtn.classList.add("error");
    syncLabel.textContent = "Erreur de connexion";
  }

  syncSpinner.hidden = true;
  await refreshStatus();

  setTimeout(() => {
    syncBtn.classList.remove("success", "error");
    syncLabel.textContent = "Synchroniser les wikis";
    syncBtn.disabled = false;
  }, 2500);
}

syncBtn.addEventListener("click", triggerSync);

// --- App config (instance GitLab, titre) ------------------------------------------

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
    // /api/config indisponible : on garde les valeurs par défaut, sans bloquer l'UI.
  }
}

// --- Init ---------------------------------------------------------------------------

updateSendButtonState();
loadConfig();
refreshStatus();
setInterval(refreshStatus, 30000);
