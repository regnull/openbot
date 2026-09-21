/**
 * Global custom-caret overlay.
 *
 * Listens (via event delegation) for focus on any `<input>` or `<textarea>`,
 * then renders a fixed-position `<div>` that tracks the caret's pixel position
 * using the mirror-element technique in `lib/caretPosition.ts`.
 *
 * The overlay pulses smoothly via a 2-second CSS animation (cursor-pulse).
 * On each keystroke the animation freezes briefly (200 ms) for tactile
 * feedback, then resumes where it left off.  Native carets are hidden via
 * `caret-color: transparent` in the base stylesheet.
 *
 * This component renders nothing to the React tree — all DOM work is
 * imperative so it stays out of the reconciliation path.
 */

import { useEffect } from "react";
import { getCaretMetrics } from "../lib/caretPosition";

/** Live check so runtime preference changes are respected. */
const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** How long the pulse freezes after each keystroke (ms). */
const PAUSE_MS = 200;

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
    let pauseTimer = 0;

    // ── Helpers ────────────────────────────────────────────────────────────
    /** Show the overlay and ensure the CSS animation is running. */
    const show = () => {
      overlay.style.display = "";
      if (prefersReducedMotion()) {
        overlay.style.opacity = "1";
      } else {
        overlay.style.animation = "";
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

    /** Pause the pulse animation for PAUSE_MS, then let it resume. */
    const pausePulse = () => {
      if (prefersReducedMotion()) return;
      clearTimeout(pauseTimer);
      overlay.classList.add("custom-caret-paused");
      pauseTimer = window.setTimeout(() => {
        overlay.classList.remove("custom-caret-paused");
      }, PAUSE_MS);
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
      // Clear any stale paused state from a prior blur-during-typing cycle.
      overlay.classList.remove("custom-caret-paused");
      t.addEventListener("scroll", schedule, { passive: true });
      schedule();
    };

    const onFocusOut = (e: FocusEvent) => {
      // `active` is reassigned by the listeners, so TS cannot narrow it
      // through the comparison alone.
      if (!active || e.target !== active) return;
      active.removeEventListener("scroll", schedule);
      active = null;
      hide();
      clearTimeout(pauseTimer);
      overlay.classList.remove("custom-caret-paused");
    };

    /** Typing: update position + freeze pulse briefly for feedback. */
    const onInput = () => {
      if (active) {
        schedule();
        pausePulse();
      }
    };

    const onSelectionChange = () => {
      if (active) schedule();
    };

    /** Mouse click: brief pause for tactile feedback (same as typing). */
    const onMouseUp = () => {
      if (active) {
        schedule();
        pausePulse();
      }
    };

    const onResize = () => {
      if (active) schedule();
    };

    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("input", onInput, { passive: true });
    document.addEventListener("keyup", onInput, { passive: true });
    document.addEventListener("mouseup", onMouseUp, { passive: true });
    document.addEventListener("selectionchange", onSelectionChange);
    window.addEventListener("resize", onResize, { passive: true });

    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("input", onInput);
      document.removeEventListener("keyup", onInput);
      document.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("selectionchange", onSelectionChange);
      window.removeEventListener("resize", onResize);
      active?.removeEventListener("scroll", schedule);
      cancelAnimationFrame(raf);
      clearTimeout(pauseTimer);
      overlay.remove();
    };
  }, []);

  return null;
}
