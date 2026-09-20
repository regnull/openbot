import type { ComponentProps, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { backendUnavailableMessage, isUnavailableErrorText } from "../lib/backendFallback";

/* ── Form controls ─────────────────────────────────────────────────────────────
   Mono, flat, hairline. Focus is the accent border plus a 1px ring, never a thick glow. */
const control = "w-full rounded-ui border border-line bg-surface px-3 text-[13px] text-fg placeholder:text-faint outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-60";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={`${control} h-9 ${p.className ?? ""}`} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={`${control} py-2 leading-relaxed ${p.className ?? ""}`} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={`${control} h-9 ${p.className ?? ""}`} />;

/* ── Buttons ───────────────────────────────────────────────────────────────── */
const variants = {
  primary: "border-accent bg-accent text-on-accent hover:border-accent-strong hover:bg-accent-strong",
  secondary: "border-line bg-transparent text-fg hover:border-line-strong hover:bg-sunken",
  danger: "border-danger/40 bg-transparent text-danger hover:border-danger hover:bg-danger/10",
  ghost: "border-transparent bg-transparent text-muted hover:bg-sunken hover:text-fg",
};
const sizes = { md: "h-9 px-3 text-[13px]", sm: "h-7 px-2 text-xs" };
export type ButtonProps = ComponentProps<"button"> & { variant?: keyof typeof variants; size?: keyof typeof sizes };
export const Button = ({ variant = "primary", size = "md", className = "", ...p }: ButtonProps) =>
  <button type={p.type ?? "button"} {...p} className={`inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-ui border font-medium leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`} />;

/** A square button holding only an icon. Always give it an aria-label. */
export const IconButton = ({ className = "", size = "md", ...p }: ComponentProps<"button"> & { size?: "md" | "sm" }) =>
  <button type={p.type ?? "button"} {...p} className={`inline-flex shrink-0 items-center justify-center rounded-ui border border-transparent text-muted transition-colors hover:bg-sunken hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 ${size === "sm" ? "h-7 w-7" : "h-9 w-9"} ${className}`} />;

/* ── Text & structure ──────────────────────────────────────────────────────── */
export const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) => (
  <label className="block space-y-1.5">
    <span className="block text-xs font-medium text-muted">{label}</span>
    {children}
    {hint && <span className="block font-sans text-xs text-faint">{hint}</span>}
  </label>
);
/** A flat panel with a hairline border. The surface itself is the only emphasis; no shadow. */
export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) =>
  <div className={`rounded-ui border border-line bg-surface p-4 ${className}`}>{children}</div>;
/** Page heading row: the title on the left, actions on the right. */
export const PageTitle = ({ children, actions }: { children: ReactNode; actions?: ReactNode }) => (
  <div className="flex min-h-9 items-center justify-between gap-3">
    <h1 className="truncate text-base font-semibold tracking-tight">{children}</h1>
    {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
  </div>
);
/** Section heading with a trailing hairline, like a divider that names what follows. */
export const SectionTitle = ({ children, className = "" }: { children: ReactNode; className?: string }) =>
  <h2 className={`rule-title text-xs font-medium text-muted ${className}`}><span className="shrink-0">{children}</span></h2>;
/** Prose helper text: set in the sans, muted. */
export const Hint = ({ children, className = "" }: { children: ReactNode; className?: string }) =>
  <p className={`font-sans text-[13px] leading-relaxed text-muted ${className}`}>{children}</p>;
export const Kbd = ({ children }: { children: ReactNode }) =>
  <kbd className="inline-block rounded-ui border border-line bg-sunken px-1 text-[10px] leading-4 text-muted">{children}</kbd>;
/** An empty screen is an invitation to act: say what belongs here and how to get it. */
export const EmptyState = ({ children, className = "" }: { children: ReactNode; className?: string }) =>
  <div className={`rounded-ui border border-dashed border-line-strong/70 px-5 py-6 font-sans text-[13px] leading-relaxed text-muted ${className}`}>{children}</div>;

/* ── Status ────────────────────────────────────────────────────────────────── */
const toneClasses = {
  zinc: { text: "text-muted", dot: "bg-line-strong" },
  green: { text: "text-ok", dot: "bg-ok" },
  amber: { text: "text-warn", dot: "bg-warn" },
  red: { text: "text-danger", dot: "bg-danger" },
  blue: { text: "text-info", dot: "bg-info" },
};
export type BadgeTone = keyof typeof toneClasses;
/** A status word with its dot: `● running`. The word carries the meaning; the dot only echoes it. */
export const Badge = ({ children, tone = "zinc", pulse = false }: { children: ReactNode; tone?: BadgeTone; pulse?: boolean }) => (
  <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-ui border border-line bg-surface px-1.5 py-px text-[11px] leading-4 ${toneClasses[tone].text}`}>
    <span className={`h-1.5 w-1.5 rounded-full ${toneClasses[tone].dot} ${pulse ? "animate-pulse" : ""}`} aria-hidden />
    {children}
  </span>
);
export const Spinner = ({ className = "" }: { className?: string }) =>
  <span role="progressbar" aria-label="Loading" className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent ${className}`} />;
export const ErrorText = ({ error }: { error: unknown }) => {
  if (!error) return null;
  const raw = String((error as Error).message ?? error);
  // Backend down/restarting: show friendly copy instead of the raw response body.
  return <p role="alert" className="text-xs leading-relaxed text-danger">{isUnavailableErrorText(raw) ? backendUnavailableMessage : raw}</p>;
};
export const OfflineNotice = () => (
  <p className="text-xs text-warn" data-testid="backend-unavailable">{backendUnavailableMessage}</p>
);

/* ── Overlay dialog ────────────────────────────────────────────────────────── */
export const Dialog = ({ title, titleId, onClose, children, as = "div", onSubmit, className = "" }: {
  title: ReactNode; titleId: string; onClose: () => void; children: ReactNode; as?: "div" | "form"; onSubmit?: (e: React.FormEvent<HTMLFormElement>) => void; className?: string;
}) => {
  const panelClass = `flex w-full max-w-lg flex-col gap-4 rounded-ui border border-line bg-surface p-5 shadow-[0_24px_60px_-20px_rgb(0_0_0/0.5)] ${className}`;
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  const inner = (
    <>
      <div className="flex items-start justify-between gap-3">
        <h2 id={titleId} className="text-sm font-semibold">{title}</h2>
        <IconButton size="sm" aria-label="Close" onClick={onClose} className="-mr-1 -mt-1">
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </IconButton>
      </div>
      {children}
    </>
  );
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      {as === "form"
        ? <form className={panelClass} onClick={stop} onSubmit={onSubmit}>{inner}</form>
        : <div className={panelClass} onClick={stop}>{inner}</div>}
    </div>
  );
};
