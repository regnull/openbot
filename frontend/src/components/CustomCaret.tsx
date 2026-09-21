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
    overlay.classList.add("custom-caret-overlay");
    Object.assign(overlay.style, {
      position: "fixed",
      width: "2px",
      pointerEvents: "none",
      zIndex: "9999",
      borderRadius: "1px",
      display: "none",
    });
    document.body.appendChild(overlay);

    // ── State ──────────────────────────────────────────────────────────────
    let active: HTMLInputElement | HTMLTextAreaElement | null = null;
    let raf = 0;

    // ── Helpers ────────────────────────────────────────────────────────────
    const show = () => {
      overlay.style.display = "";
      if (!REDUCED_MOTION) {
        // Restart the CSS fade animation so the caret blinks fresh on each
        // position update (keystroke / click).
        overlay.style.animation = "none";
        // Force a reflow so the browser registers the reset before we
        // re-enable the animation.
        void overlay.offsetHeight;
        overlay.style.animation = "";
      } else {
        overlay.style.opacity = "1";
      }
    };

    const hide = () => {
      overlay.style.display = "none";
    };

    const update = () => {
      raf = 0;
      if (!active) return;

      const m = getCaretMetrics(active);
      if (!m) {
        hide();
        return;
      }

      overlay.style.top = `${m.top}px`;
      overlay.style.left = `${m.left}px`;
      overlay.style.height = `${m.height}px`;
      overlay.style.backgroundColor = m.color;
      show();
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
      // `active` is reassigned by the listeners, so TS cannot narrow it through the comparison alone.
      if (!active || e.target !== active) return;
      active.removeEventListener("scroll", schedule);
      active = null;
      hide();
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
      active?.removeEventListener("scroll", schedule);
      cancelAnimationFrame(raf);
      overlay.remove();
    };
  }, []);

  return null;
}
