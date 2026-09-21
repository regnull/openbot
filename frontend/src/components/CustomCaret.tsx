/**
 * Global custom-caret overlay.
 *
 * Listens (via event delegation) for focus on any `<input>` or `<textarea>`,
 * then renders a fixed-position `<div>` that tracks the caret's pixel position
 * using the mirror-element technique in `lib/caretPosition.ts`.
 *
 * The overlay is styled with the shared `.caret` class (index.css) — the same
 * pulsing block used as the decorative streaming cursor in RunCard when a bot
 * is writing its reply, so both read as one cursor. Its width and height are
 * `em`-relative, so the overlay's `font-size` is set to the focused element's
 * own computed font size on every reposition; everything else (color, the
 * pulse animation, reduced-motion handling) comes from that one class. Native
 * carets are hidden via `caret-color: transparent` in the base stylesheet.
 *
 * This component renders nothing to the React tree — all DOM work is
 * imperative so it stays out of the reconciliation path.
 */

import { useEffect } from "react";
import { getCaretMetrics } from "../lib/caretPosition";

export default function CustomCaret() {
  useEffect(() => {
    // ── Overlay element ────────────────────────────────────────────────────
    const overlay = document.createElement("div");
    overlay.setAttribute("aria-hidden", "true");
    overlay.classList.add("caret");
    Object.assign(overlay.style, { position: "fixed", pointerEvents: "none", zIndex: "9999", display: "none" });
    document.body.appendChild(overlay);

    // ── State ──────────────────────────────────────────────────────────────
    let active: HTMLInputElement | HTMLTextAreaElement | null = null;
    let raf = 0;

    // ── Helpers ────────────────────────────────────────────────────────────
    const update = () => {
      raf = 0;
      if (!active) return;

      const m = getCaretMetrics(active);
      if (!m) {
        overlay.style.display = "none";
        return;
      }

      overlay.style.top = `${m.top}px`;
      overlay.style.left = `${m.left}px`;
      // `.caret`'s width/height are em-relative, matched to the font size they're drawn at
      // (RunCard's streaming text); this is what makes the two cursors the same size.
      overlay.style.fontSize = window.getComputedStyle(active).fontSize;
      overlay.style.display = "";
    };

    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };

    // ── Delegated listeners ────────────────────────────────────────────────
    const onFocusIn = (e: FocusEvent) => {
      const t = e.target;
      if (
        !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)
      )
        return;
      if (t.type === "password" || t.disabled || t.readOnly) return;

      active = t;
      t.addEventListener("scroll", schedule, { passive: true });
      schedule();
    };

    const onFocusOut = (e: FocusEvent) => {
      // `active` is reassigned by the listeners, so TS cannot narrow it
      // through the comparison alone.
      if (!active || e.target !== active) return;
      active.removeEventListener("scroll", schedule);
      active = null;
      overlay.style.display = "none";
    };

    const onActivity = () => {
      if (active) schedule();
    };

    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("input", onActivity, { passive: true });
    document.addEventListener("keyup", onActivity, { passive: true });
    document.addEventListener("mouseup", onActivity, { passive: true });
    document.addEventListener("selectionchange", onActivity);
    window.addEventListener("resize", onActivity, { passive: true });

    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("input", onActivity);
      document.removeEventListener("keyup", onActivity);
      document.removeEventListener("mouseup", onActivity);
      document.removeEventListener("selectionchange", onActivity);
      window.removeEventListener("resize", onActivity);
      active?.removeEventListener("scroll", schedule);
      cancelAnimationFrame(raf);
      overlay.remove();
    };
  }, []);

  return null;
}
