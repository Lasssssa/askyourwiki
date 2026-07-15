// Typed helpers for the FastAPI backend.

/**
 * Wraps fetch so an expired/missing session sends the user back to the login
 * page instead of leaving them stuck on the chat with silent 401s. The backend
 * protects every /api/ route once auth is enabled, so any 401 means the session
 * is gone.
 */
async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, init);
  if (response.status === 401 && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
  return response;
}

export type Role = "user" | "assistant" | "error";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface AppStatus {
  pages_indexed?: number;
  last_sync_at?: string | null;
  is_syncing?: boolean;
  last_sync_errors?: string[];
  auth_enabled?: boolean;
}

export interface AppConfig {
  gitlab_url?: string;
  title?: string;
  history_enabled?: boolean;
}

export interface SyncResult {
  pages_indexed?: number;
  error?: string;
}

export async function fetchStatus(): Promise<AppStatus> {
  const response = await apiFetch("/api/status");
  if (!response.ok) throw new Error(`Server error (${response.status}).`);
  return response.json();
}

export async function fetchConfig(): Promise<AppConfig> {
  const response = await apiFetch("/api/config");
  if (!response.ok) throw new Error(`Server error (${response.status}).`);
  return response.json();
}

export interface CurrentUser {
  username: string;
  name?: string | null;
  avatar_url?: string | null;
  web_url?: string | null;
}

/** The signed-in GitLab user, or null when authentication is disabled. */
export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const response = await apiFetch("/api/me");
  if (!response.ok) return null;
  const data = await response.json().catch(() => ({}));
  return data && data.username ? (data as CurrentUser) : null;
}

export async function triggerSync(): Promise<{ ok: boolean; data: SyncResult }> {
  const response = await apiFetch("/api/sync", { method: "POST" });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

export async function logout(): Promise<void> {
  await apiFetch("/api/logout", { method: "POST" });
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

interface StoredMessage {
  role: string;
  content: string;
  ts?: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: StoredMessage[];
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const response = await apiFetch("/api/conversations");
  if (!response.ok) return [];
  const data = await response.json().catch(() => ({}));
  return data.conversations ?? [];
}

export async function fetchConversation(id: string): Promise<ConversationDetail | null> {
  const response = await apiFetch(`/api/conversations/${encodeURIComponent(id)}`);
  if (!response.ok) return null;
  return response.json();
}

export async function deleteConversation(id: string): Promise<boolean> {
  const response = await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  return response.ok;
}

export type ChatEvent = { delta: string } | { error: string };

/**
 * Sends a chat message and yields streamed SSE events (deltas and errors)
 * until the server closes the stream. `conversationId` groups turns of the same
 * chat together so the server can persist them under one conversation.
 */
export async function* streamChat(
  message: string,
  history: ChatMessage[],
  conversationId: string
): AsyncGenerator<ChatEvent> {
  const response = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history, conversation_id: conversationId }),
  });

  if (!response.ok || !response.body) {
    let detail = "";
    try {
      const errBody = await response.json();
      detail = errBody.error || errBody.detail || "";
    } catch {
      // no usable JSON body
    }
    yield { error: detail || `Server error (${response.status}).` };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? ""; // last incomplete fragment

    for (const chunk of chunks) {
      if (!chunk.startsWith("data: ")) continue;
      const payload = chunk.slice(6);
      if (payload === "[DONE]") continue;

      let data: ChatEvent;
      try {
        data = JSON.parse(payload);
      } catch {
        continue;
      }
      yield data;
    }
  }
}
