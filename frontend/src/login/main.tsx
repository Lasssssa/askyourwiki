import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../styles/base.css";
import "../styles/login.css";

import { LoginPage } from "./LoginPage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LoginPage />
  </StrictMode>
);
