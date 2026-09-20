/**
 * Global custom-caret overlay.
 *
 * Listens (via event delegation) for focus on any `<input>` or `<textarea>`,
 * then renders a fixed-position `<div>` that tracks the caret's pixel position
 * using the mirror-element technique in `lib/caretPosition.ts`.
 *
 * The overlay fades in/out smoothly (CSS animation) and inherits the input's
 * text colour.  Native carets are hidden via `caret-color: transparent` in the
 * base stylesheet.
 *
 * This component renders nothing to the React tree — all DOM work is
 * imperative so it stays out of the reconciliation path.
 */

import { useEffect } from "react";
import { getCaretMetrics } from "../lib/caretPosition";

const REDUCED_MOTION =
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export default function CustomCaret() {
  useEffect(() => {
    // ── Overlay element ────────────────────────────────────────────────────
    const overlay = document.createElement("div");
    overlay.setAttribute("aria-hidden", "true");
    Object.assign(overlay.style, {
      position: "fixed",
      width: "2px",
      pointerEvents: "none",
      zIndex: "9999",
      borderRadius: "1px",
      opacity: "0",
    });
    if (!REDUCED_MOTION) {
      overlay.style.animation = "caret-fade 1s ease-in-out infinite";
    }
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
        overlay.style.opacity = "0";
        return;
      }

      overlay.style.top = `${m.top}px`;
      overlay.style.left = `${m.left}px`;
      overlay.style.height = `${m.height}px`;
      overlay.style.backgroundColor = m.color;

      // When reduced-motion is preferred, drive opacity imperatively instead
      // of relying on the CSS animation.
      if (REDUCED_MOTION) {
        overlay.style.opacity = "1";
      }
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
      if (e.target !== active) return;
      active.removeEventListener("scroll", schedule);
      active = null;
      overlay.style.opacity = "0";
    };

    const onInput = () => {
      if (active) schedule();
    };

    const onSelectionChange = () => {
      if (active) schedule();
    };

    const onResize = () => {
      if (active) schedule();
    };

    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("input", onInput, { passive: true });
    document.addEventListener("keyup", onInput, { passive: true });
    document.addEventListener("mouseup", onInput, { passive: true });
    document.addEventListener("selectionchange", onSelectionChange);
    window.addEventListener("resize", onResize, { passive: true });

    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("input", onInput);
      document.removeEventListener("keyup", onInput);
      document.removeEventListener("mouseup", onInput);
      document.removeEventListener("selectionchange", onSelectionChange);
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(raf);
      overlay.remove();
    };
  }, []);

  return null;
}
