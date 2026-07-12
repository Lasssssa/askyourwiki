import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchConfig,
  fetchStatus,
  streamChat,
  type AppConfig,
  type AppStatus,
  type ChatMessage,
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

export function App() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [config, setConfig] = useState<AppConfig>({});
  const [sidebarVisible, setSidebarVisible] = useState(false);

  // Completed user/assistant turns, sent back to the API as conversation history.
  const historyRef = useRef<ChatMessage[]>([]);
  const chatAreaRef = useRef<HTMLElement>(null);

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
        for await (const event of streamChat(message, historyRef.current)) {
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
    [isStreaming]
  );

  const startNewChat = useCallback(() => {
    if (isStreaming) return;
    historyRef.current = [];
    setMessages([]);
  }, [isStreaming]);

  return (
    <div className={`app${sidebarVisible ? " sidebar-visible" : ""}`}>
      <Sidebar
        status={status}
        config={config}
        onNewChat={startNewChat}
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
