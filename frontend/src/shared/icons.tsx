// Inline SVG icons shared across pages.

export function BrandLogo({ size = 22 }: { size?: number }) {
  return (
    <svg
      className="brand-logo"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M22.65 10.31 12 18.71 1.35 10.31a.84.84 0 0 1-.31-.94l1.71-5.27a.42.42 0 0 1 .8 0l1.72 5.27h6.46l1.72-5.27a.42.42 0 0 1 .8 0l1.72 5.27a.84.84 0 0 1-.32.94Z" />
    </svg>
  );
}

interface StrokeIconProps {
  size?: number;
  children: React.ReactNode;
}

function StrokeIcon({ size = 16, children }: StrokeIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function PlusIcon() {
  return (
    <StrokeIcon>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </StrokeIcon>
  );
}

export function MenuIcon() {
  return (
    <StrokeIcon size={18}>
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </StrokeIcon>
  );
}

export function LogoutIcon() {
  return (
    <StrokeIcon>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </StrokeIcon>
  );
}

export function SendIcon() {
  return (
    <StrokeIcon size={18}>
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </StrokeIcon>
  );
}

export function ErrorIcon() {
  return (
    <StrokeIcon>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </StrokeIcon>
  );
}

export function ChatIcon({ size = 15 }: { size?: number }) {
  return (
    <StrokeIcon size={size}>
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" />
    </StrokeIcon>
  );
}

export function TrashIcon({ size = 14 }: { size?: number }) {
  return (
    <StrokeIcon size={size}>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </StrokeIcon>
  );
}
