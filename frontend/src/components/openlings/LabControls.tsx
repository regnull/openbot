import type { ReactNode } from "react";

/** A labelled group of toolbar buttons. */
export function ControlGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-2">
      <span className="hidden text-[10px] font-medium uppercase tracking-[0.08em] text-faint lg:inline">{label}</span>
      <div className="flex items-center rounded-ui border border-line bg-surface p-0.5">{children}</div>
    </div>
  );
}

/** A toolbar button; `active` marks the current choice (aria-pressed). */
export function ToolButton({ active = false, onClick, children, title }: { active?: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      className={`h-7 whitespace-nowrap rounded-[2px] px-2.5 text-xs leading-none transition-colors ${active ? "bg-fg text-canvas" : "text-muted hover:bg-sunken hover:text-fg"}`}
    >
      {children}
    </button>
  );
}
