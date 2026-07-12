import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// Multi-page build: the chat app (index.html) and the login page (login.html)
// are served as two separate documents by the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("index.html", import.meta.url)),
        login: fileURLToPath(new URL("login.html", import.meta.url)),
      },
    },
  },
  server: {
    // In development, API and auth requests are proxied to the FastAPI server.
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
    },
  },
});
