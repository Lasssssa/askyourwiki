import { useState } from "react";

import { BrandLogo, ErrorIcon } from "../shared/icons";

function errorFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("error");
}

export function LoginPage() {
  const [error] = useState<string | null>(errorFromUrl);

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <BrandLogo size={28} />
        </div>
        <h1>AskYourWiki</h1>
        <p className="login-subtitle">Sign in to continue</p>

        {error && (
          <div className="login-error">
            <ErrorIcon />
            <span>{error}</span>
          </div>
        )}

        <a className="login-gitlab-btn" href="/auth/gitlab">
          <BrandLogo size={18} />
          <span>Sign in with GitLab</span>
        </a>
      </div>
    </div>
  );
}
