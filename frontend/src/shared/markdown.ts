// Markdown rendering with syntax highlighting, sanitized before injection.

import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";
import { Marked } from "marked";
import { markedHighlight } from "marked-highlight";

const marked = new Marked(
  markedHighlight({
    langPrefix: "hljs language-",
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : "plaintext";
      return hljs.highlight(code, { language }).value;
    },
  })
);

marked.setOptions({ breaks: true, gfm: true });

export function renderMarkdown(text: string): string {
  const html = marked.parse(text || "", { async: false });
  return DOMPurify.sanitize(html);
}
