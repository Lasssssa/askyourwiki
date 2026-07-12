import { useEffect, useState, type FormEvent } from "react";

import { fetchLoginOptions, login, type LoginOptions } from "../shared/api";
import { BrandLogo, ErrorIcon } from "../shared/icons";

// Shown until /api/login-options responds; the password form is the safe default.
const FALLBACK_OPTIONS: LoginOptions = { password: true, gitlab: false };

function errorFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("error");
}

export function LoginPage() {
  const [options, setOptions] = useState<LoginOptions | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(errorFromUrl);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchLoginOptions()
      .then(setOptions)
      .catch(() => setOptions(FALLBACK_OPTIONS));
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const result = await login(username, password);
      if (result.ok) {
        window.location.href = "/";
        return;
      }
      setError(result.error || "Sign in failed.");
    } catch (err) {
      setError(`Connection error: ${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const showPassword = options?.password ?? false;
  const showGitlab = options?.gitlab ?? false;

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
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

        {showGitlab && (
          <a className="login-gitlab-btn" href="/auth/gitlab">
            <BrandLogo size={18} />
            <span>Sign in with GitLab</span>
          </a>
        )}

        {showGitlab && showPassword && <div className="login-divider">or</div>}

        {showPassword && (
          <>
            <label className="login-field">
              <span>Username</span>
              <div className="login-field-input">
                <input
                  name="username"
                  type="text"
                  autoComplete="username"
                  required
                  autoFocus={!showGitlab}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </div>
            </label>

            <label className="login-field">
              <span>Password</span>
              <div className="login-field-input">
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
            </label>

            <button type="submit" className="login-submit" disabled={submitting}>
              Sign in
            </button>
          </>
        )}
      </form>
    </div>
  );
}
