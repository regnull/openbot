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
 * Repositioned every animation frame while an element is focused, not on
 * discrete DOM events: a controlled React input can have its value cleared
 * (e.g. the composer resetting the textarea after Enter) without firing a
 * real "input" or "selectionchange" event, since React writes `.value`
 * directly rather than simulating user input. Listening for specific events
 * left the overlay stuck at its last real position after such a clear;
 * polling on rAF stays correct regardless of what moved the caret, and costs
 * nothing while no input is focused (rAF runs only then, and pauses on a
 * hidden tab).
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

    // ── Loop ───────────────────────────────────────────────────────────────
    const loop = () => {
      raf = 0;
      if (!active) return;

      const m = getCaretMetrics(active);
      if (!m) {
        overlay.style.display = "none";
      } else {
        overlay.style.display = "";
        // `.caret`'s width/height are em-relative, matched to the font size they're drawn at
        // (RunCard's streaming text); this is what makes the two cursors the same size.
        overlay.style.fontSize = window.getComputedStyle(active).fontSize;
        overlay.style.left = `${m.left}px`;
        // `m.textBottom` is the same "text-bottom" reference `.caret` aligns itself to inline
        // (see caretPosition.ts); place the overlay's own bottom edge there, so a `position:
        // fixed` overlay renders at the exact spot the class would if it were inline.
        overlay.style.top = `${m.textBottom - overlay.offsetHeight}px`;
      }
      raf = requestAnimationFrame(loop);
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
      if (!raf) raf = requestAnimationFrame(loop);
    };

    const onFocusOut = (e: FocusEvent) => {
      // `active` is reassigned by the listeners, so TS cannot narrow it
      // through the comparison alone.
      if (!active || e.target !== active) return;
      active = null;
      overlay.style.display = "none";
    };

    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);

    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      cancelAnimationFrame(raf);
      overlay.remove();
    };
  }, []);

  return null;
}
