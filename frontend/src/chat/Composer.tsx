import { useRef, useState } from "react";

import { SendIcon } from "../shared/icons";

const TEXTAREA_MAX_HEIGHT_PX = 200;

interface ComposerProps {
  disabled: boolean;
  onSend: (message: string) => void;
}

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
  };

  const send = () => {
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
    requestAnimationFrame(autoResize);
    textareaRef.current?.focus();
  };

  return (
    <footer className="composer">
      <div className="composer-inner">
        <textarea
          ref={textareaRef}
          className="composer-input"
          placeholder="Type your message... (Shift+Enter for a new line)"
          rows={1}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            autoResize();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button
          className="send-btn"
          aria-label="Send message"
          disabled={disabled || value.trim().length === 0}
          onClick={send}
        >
          <SendIcon />
        </button>
      </div>
      <p className="composer-hint">The assistant can make mistakes. Check important information.</p>
    </footer>
  );
}
