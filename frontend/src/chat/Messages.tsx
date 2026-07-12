import type { Role } from "../shared/api";
import { BrandLogo } from "../shared/icons";
import { renderMarkdown } from "../shared/markdown";

export interface DisplayMessage {
  id: number;
  role: Role;
  content: string;
  streaming?: boolean;
}

function avatarTextForRole(role: Role): string {
  if (role === "user") return "🧑";
  if (role === "error") return "⚠️";
  return "🤖";
}

function Bubble({ message }: { message: DisplayMessage }) {
  if (message.role === "assistant") {
    const html =
      renderMarkdown(message.content) + (message.streaming ? '<span class="cursor"></span>' : "");
    return <div className="bubble" dangerouslySetInnerHTML={{ __html: html }} />;
  }
  return <div className="bubble">{message.content}</div>;
}

// Shared "avatar + bubble column" layout for a message row; user messages
// have their parts reversed so they appear on the right.
function MessageRow({ message }: { message: DisplayMessage }) {
  const avatar = (
    <div className="avatar">{avatarTextForRole(message.role)}</div>
  );
  const col = (
    <div className="bubble-col">
      <Bubble message={message} />
    </div>
  );

  return (
    <div className={`message ${message.role}`}>
      {message.role === "user" ? (
        <>
          {col}
          {avatar}
        </>
      ) : (
        <>
          {avatar}
          {col}
        </>
      )}
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="message assistant">
      <div className="avatar">🤖</div>
      <div className="bubble-col">
        <div className="bubble">
          <div className="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <div className="welcome-logo">
        <BrandLogo />
      </div>
      <h2>Ask a question about your wikis</h2>
      <p>Answers are generated from the content of the indexed GitLab wikis.</p>
    </div>
  );
}

interface MessagesProps {
  messages: DisplayMessage[];
  isTyping: boolean;
}

export function Messages({ messages, isTyping }: MessagesProps) {
  if (messages.length === 0 && !isTyping) {
    return (
      <div className="messages">
        <Welcome />
      </div>
    );
  }

  return (
    <div className="messages">
      {messages.map((message) => (
        <MessageRow key={message.id} message={message} />
      ))}
      {isTyping && <TypingIndicator />}
    </div>
  );
}
