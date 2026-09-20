/**
 * Measures the pixel position of the caret (cursor) inside an `<input>` or
 * `<textarea>` using a hidden mirror-element technique.
 *
 * The mirror copies the element's computed styles and text, inserting a
 * zero-width sentinel at the caret offset.  Measuring the sentinel's bounding
 * rect gives us viewport-relative coordinates for the caret.
 */

let mirror: HTMLDivElement | null = null;

function getMirror(): HTMLDivElement {
  if (!mirror) {
    mirror = document.createElement("div");
    mirror.setAttribute("aria-hidden", "true");
    Object.assign(mirror.style, {
      position: "fixed",
      top: "0",
      left: "0",
      visibility: "hidden",
      whiteSpace: "pre-wrap",
      wordWrap: "break-word",
      overflow: "hidden",
    });
    document.body.appendChild(mirror);
  }
  return mirror;
}

/** CSS properties to clone from the target element onto the mirror. */
const STYLE_PROPS = [
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "letter-spacing",
  "text-transform",
  "word-spacing",
  "text-indent",
  "line-height",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "border-top-width",
  "border-right-width",
  "border-bottom-width",
  "border-left-width",
  "box-sizing",
];

export interface CaretMetrics {
  /** Top edge in viewport coordinates. */
  top: number;
  /** Left edge in viewport coordinates. */
  left: number;
  /** Height of the caret line (matches line-height). */
  height: number;
  /** Computed text color of the element. */
  color: string;
}

/**
 * Return the viewport-relative position of the caret inside `el`, or `null`
 * when the element doesn't support a visible caret (password, disabled,
 * read-only) or when a range is selected rather than a collapsed caret.
 */
export function getCaretMetrics(
  el: HTMLInputElement | HTMLTextAreaElement,
): CaretMetrics | null {
  if (el.type === "password" || el.disabled || el.readOnly) return null;

  const pos = el.selectionStart;
  if (pos === null || el.selectionEnd !== pos) return null;

  const computed = window.getComputedStyle(el);
  const m = getMirror();

  // Clone styles ──────────────────────────────────────────────────────────
  for (const prop of STYLE_PROPS) {
    m.style.setProperty(prop, computed.getPropertyValue(prop));
  }

  const isTextarea = el instanceof HTMLTextAreaElement;
  m.style.width = isTextarea ? `${el.clientWidth}px` : "";
  m.style.whiteSpace = isTextarea ? "pre-wrap" : "pre";
  m.style.wordWrap = isTextarea ? "break-word" : "normal";

  // Build mirrored content with a zero-width sentinel at the caret offset ─
  m.textContent = "";
  m.appendChild(document.createTextNode(el.value.substring(0, pos)));

  const marker = document.createElement("span");
  marker.textContent = "\u200b";
  m.appendChild(marker);

  m.appendChild(document.createTextNode(el.value.substring(pos)));

  // Measure ───────────────────────────────────────────────────────────────
  const markerRect = marker.getBoundingClientRect();
  const mirrorRect = m.getBoundingClientRect();
  const elRect = el.getBoundingClientRect();

  const contentX = markerRect.left - mirrorRect.left;
  const contentY = markerRect.top - mirrorRect.top;

  const borderTop = parseFloat(computed.borderTopWidth) || 0;
  const borderLeft = parseFloat(computed.borderLeftWidth) || 0;

  const metrics: CaretMetrics = {
    top: elRect.top + borderTop + contentY - el.scrollTop,
    left: elRect.left + borderLeft + contentX - el.scrollLeft,
    height: markerRect.height,
    color: computed.color,
  };

  // Keep the mirror element alive for reuse; just clear its content.
  m.textContent = "";

  return metrics;
}
