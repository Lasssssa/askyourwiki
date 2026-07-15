import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteConversation,
  fetchConfig,
  fetchConversation,
  fetchConversations,
  fetchCurrentUser,
  fetchStatus,
  streamChat,
  type AppConfig,
  type AppStatus,
  type ChatMessage,
  type ConversationSummary,
  type CurrentUser,
  type Role,
} from "../shared/api";
import { MenuIcon } from "../shared/icons";
import { Composer } from "./Composer";
import { Messages, type DisplayMessage } from "./Messages";
import { Sidebar } from "./Sidebar";

const STATUS_REFRESH_INTERVAL_MS = 30000;

let nextMessageId = 1;

function makeMessage(role: Role, content: string, streaming = false): DisplayMessage {
  return { id: nextMessageId++, role, content, streaming };
}

function newConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function App() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [config, setConfig] = useState<AppConfig>({});
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string>(newConversationId);
  const [sidebarVisible, setSidebarVisible] = useState(false);

  // Completed user/assistant turns, sent back to the API as conversation history.
  const historyRef = useRef<ChatMessage[]>([]);
  const chatAreaRef = useRef<HTMLElement>(null);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await fetchConversations());
    } catch {
      // History unavailable: leave the list as-is rather than blocking the chat.
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await fetchStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(refreshStatus, STATUS_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshStatus]);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() => {
        // /api/config unavailable: keep the default values without blocking the UI.
      });
  }, []);

  useEffect(() => {
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    const el = chatAreaRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isTyping]);

  const sendMessage = useCallback(
    async (rawMessage: string) => {
      const message = rawMessage.trim();
      if (!message || isStreaming) return;

      setMessages((prev) => [...prev, makeMessage("user", message)]);
      setIsStreaming(true);
      setIsTyping(true);

      let assistantText = "";
      let assistantId: number | null = null;

      const updateAssistant = (content: string, streaming: boolean) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content, streaming } : m))
        );
      };

      try {
        for await (const event of streamChat(message, historyRef.current, conversationId)) {
          if ("error" in event && event.error) {
            setIsTyping(false);
            setMessages((prev) => [...prev, makeMessage("error", event.error)]);
            continue;
          }

          if ("delta" in event && event.delta) {
            assistantText += event.delta;
            if (assistantId === null) {
              setIsTyping(false);
              const created = makeMessage("assistant", assistantText, true);
              assistantId = created.id;
              setMessages((prev) => [...prev, created]);
            } else {
              updateAssistant(assistantText, true);
            }
          }
        }

        if (assistantId !== null) {
          updateAssistant(assistantText, false);
        }

        if (assistantText) {
          historyRef.current.push(
            { role: "user", content: message },
            { role: "assistant", content: assistantText }
          );
          // The server has now persisted this turn: refresh the history list so
          // a brand-new conversation appears (and its title shows up).
          refreshConversations();
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage("error", `Connection error: ${(err as Error).message}`),
        ]);
      } finally {
        setIsTyping(false);
        setIsStreaming(false);
      }
    },
    [isStreaming, conversationId, refreshConversations]
  );

  const startNewChat = useCallback(() => {
    if (isStreaming) return;
    historyRef.current = [];
    setMessages([]);
    setConversationId(newConversationId());
  }, [isStreaming]);

  const openConversation = useCallback(
    async (id: string) => {
      if (isStreaming || id === conversationId) {
        setSidebarVisible(false);
        return;
      }
      const conversation = await fetchConversation(id);
      if (!conversation) {
        // Likely deleted in the meantime: refresh the list and bail out.
        refreshConversations();
        return;
      }

      const loaded: DisplayMessage[] = conversation.messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => makeMessage(m.role as Role, m.content));
      historyRef.current = conversation.messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as Role, content: m.content }));

      setMessages(loaded);
      setConversationId(id);
      setSidebarVisible(false);
    },
    [isStreaming, conversationId, refreshConversations]
  );

  const removeConversation = useCallback(
    async (id: string) => {
      const ok = await deleteConversation(id);
      if (!ok) return;
      await refreshConversations();
      // If the open conversation was deleted, start a fresh one.
      if (id === conversationId) {
        historyRef.current = [];
        setMessages([]);
        setConversationId(newConversationId());
      }
    },
    [conversationId, refreshConversations]
  );

  return (
    <div className={`app${sidebarVisible ? " sidebar-visible" : ""}`}>
      <Sidebar
        status={status}
        config={config}
        user={user}
        conversations={conversations}
        activeConversationId={conversationId}
        onNewChat={startNewChat}
        onOpenConversation={openConversation}
        onDeleteConversation={removeConversation}
        onStatusChanged={refreshStatus}
        onClose={() => setSidebarVisible(false)}
      />

      <div className="sidebar-overlay" onClick={() => setSidebarVisible(false)}></div>

      <div className="main">
        <header className="main-header">
          <button
            className="icon-btn sidebar-open"
            aria-label="Show menu"
            onClick={() => setSidebarVisible(true)}
          >
            <MenuIcon />
          </button>
          <h1>{config.title || "GitLab Wiki Assistant"}</h1>
        </header>

        <main className="chat-area" ref={chatAreaRef}>
          <Messages messages={messages} isTyping={isTyping} />
        </main>

        <Composer disabled={isStreaming} onSend={sendMessage} />
      </div>
    </div>
  );
}
