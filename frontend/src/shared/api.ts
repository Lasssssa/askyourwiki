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

export async function triggerSync(): Promise<{ ok: boolean; data: SyncResult }> {
  const response = await apiFetch("/api/sync", { method: "POST" });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, data };
}

export async function logout(): Promise<void> {
  await apiFetch("/api/logout", { method: "POST" });
}

export interface LoginOptions {
  password: boolean;
  gitlab: boolean;
}

export async function fetchLoginOptions(): Promise<LoginOptions> {
  const response = await apiFetch("/api/login-options");
  if (!response.ok) throw new Error(`Server error (${response.status}).`);
  return response.json();
}

export async function login(username: string, password: string): Promise<{ ok: boolean; error?: string }> {
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (response.ok) return { ok: true };
  const data = await response.json().catch(() => ({}));
  return { ok: false, error: data.error || "Sign in failed." };
}

export type ChatEvent = { delta: string } | { error: string };

/**
 * Sends a chat message and yields streamed SSE events (deltas and errors)
 * until the server closes the stream.
 */
export async function* streamChat(
  message: string,
  history: ChatMessage[]
): AsyncGenerator<ChatEvent> {
  const response = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
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
