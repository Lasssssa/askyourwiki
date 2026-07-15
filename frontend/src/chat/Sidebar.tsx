import { useEffect, useRef, useState } from "react";

import { logout, triggerSync, type AppConfig, type AppStatus, type CurrentUser } from "../shared/api";
import { BrandLogo, LogoutIcon, PlusIcon } from "../shared/icons";

const SYNC_RESET_DELAY_MS = 2500;

function formatRelativeTime(isoString?: string | null): string {
  if (!isoString) return "never";

  const date = new Date(isoString);
  const diffMin = Math.round((Date.now() - date.getTime()) / 60000);

  if (diffMin < 1) return "just now";
  if (diffMin === 1) return "1 min ago";
  if (diffMin < 60) return `${diffMin} min ago`;

  const diffHours = Math.round(diffMin / 60);
  if (diffHours === 1) return "1 hour ago";
  if (diffHours < 24) return `${diffHours} hours ago`;

  const diffDays = Math.round(diffHours / 24);
  return diffDays === 1 ? "1 day ago" : `${diffDays} days ago`;
}

type SyncState =
  | { kind: "idle" }
  | { kind: "syncing" }
  | { kind: "success"; label: string }
  | { kind: "error"; label: string };

interface SidebarProps {
  status: AppStatus | null;
  config: AppConfig;
  user: CurrentUser | null;
  onNewChat: () => void;
  onStatusChanged: () => void;
  onClose: () => void;
}

function UserCard({ user }: { user: CurrentUser }) {
  const [avatarFailed, setAvatarFailed] = useState(false);
  const displayName = user.name || user.username;
  const initial = displayName.charAt(0).toUpperCase();
  const avatar =
    user.avatar_url && !avatarFailed ? (
      <img
        className="user-avatar"
        src={user.avatar_url}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setAvatarFailed(true)}
      />
    ) : (
      <span className="user-avatar user-avatar-fallback" aria-hidden="true">
        {initial}
      </span>
    );

  const body = (
    <>
      {avatar}
      <span className="user-info">
        <span className="user-name">{displayName}</span>
        <span className="user-handle">@{user.username}</span>
      </span>
    </>
  );

  return user.web_url ? (
    <a className="user-card" href={user.web_url} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  ) : (
    <div className="user-card">{body}</div>
  );
}

export function Sidebar({ status, config, user, onNewChat, onStatusChanged, onClose }: SidebarProps) {
  const [syncState, setSyncState] = useState<SyncState>({ kind: "idle" });
  const resetTimerRef = useRef<number>(undefined);

  useEffect(() => () => clearTimeout(resetTimerRef.current), []);

  const handleSync = async () => {
    setSyncState({ kind: "syncing" });

    try {
      const { ok, data } = await triggerSync();
      if (ok) {
        setSyncState({ kind: "success", label: `${data.pages_indexed ?? 0} page(s) synced` });
      } else {
        setSyncState({ kind: "error", label: data.error || "Sync failed" });
      }
    } catch {
      setSyncState({ kind: "error", label: "Connection error" });
    }

    onStatusChanged();
    resetTimerRef.current = window.setTimeout(
      () => setSyncState({ kind: "idle" }),
      SYNC_RESET_DELAY_MS
    );
  };

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      window.location.href = "/login";
    }
  };

  const syncErrors = status?.last_sync_errors ?? [];
  const syncLabel =
    syncState.kind === "syncing"
      ? "Syncing..."
      : syncState.kind === "idle"
        ? "Sync wikis"
        : syncState.label;

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="brand">
          <BrandLogo />
          <span className="brand-name">AskYourWiki</span>
        </div>
        <button className="icon-btn sidebar-close" aria-label="Close menu" onClick={onClose}>
          ✕
        </button>
      </div>

      <button className="new-chat-btn" onClick={onNewChat}>
        <PlusIcon />
        New conversation
      </button>

      <div className="sidebar-section">
        <h2 className="sidebar-section-title">Status</h2>
        <div className="status-card">
          <div className="status-row">
            <span className="status-label">Indexed pages</span>
            <span className="status-value">{status ? (status.pages_indexed ?? 0) : "—"}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Last sync</span>
            <span className="status-value">
              {status
                ? status.is_syncing
                  ? "syncing..."
                  : formatRelativeTime(status.last_sync_at)
                : "unavailable"}
            </span>
          </div>
          {syncErrors.length > 0 && (
            <div className="status-error">{syncErrors.length} error(s) during the last sync.</div>
          )}
        </div>

        <button
          className={`sync-btn${syncState.kind === "success" ? " success" : ""}${syncState.kind === "error" ? " error" : ""}`}
          disabled={syncState.kind !== "idle"}
          onClick={handleSync}
        >
          {syncState.kind === "syncing" && <span className="spinner"></span>}
          <span>{syncLabel}</span>
        </button>
      </div>

      <div className="sidebar-footer">
        {user && <UserCard user={user} />}
        {config.gitlab_url && (
          <a
            className="gitlab-link"
            href={config.gitlab_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <BrandLogo size={16} />
            <span className="gitlab-link-text">{config.gitlab_url.replace(/^https?:\/\//, "")}</span>
          </a>
        )}
        {status?.auth_enabled && (
          <button type="button" className="logout-btn" onClick={handleLogout}>
            <LogoutIcon />
            <span>Log out</span>
          </button>
        )}
      </div>
    </aside>
  );
}
