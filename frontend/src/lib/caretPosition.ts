/**
 * Measures the pixel position of the caret (cursor) inside an `<input>` or
 * `<textarea>` using a hidden mirror-element technique.
 *
 * The mirror copies the element's computed styles and text, inserting a
 * zero-size sentinel at the caret offset. The sentinel is an inline-block
 * with `vertical-align: text-bottom` and no width or height of its own, so
 * its bounding rect collapses to a single point: the same "text-bottom"
 * reference line an inline element like the `.caret` cursor aligns itself to
 * (see index.css) -- not the top or the full height of the surrounding line
 * box, which is usually taller once a line-height beyond the font's own
 * metrics is applied (e.g. this app's `leading-relaxed` inputs). Anchoring a
 * short cursor overlay at the line box's top left it floating visibly above
 * the text; anchoring its bottom at this point instead puts it exactly where
 * `.caret` would render inline, regardless of that extra leading.
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
  /** Left edge in viewport coordinates. */
  left: number;
  /** Viewport Y of the caret's line's "text-bottom" reference -- where an element with
   * `vertical-align: text-bottom` has its own bottom edge, same as `.caret` in RunCard. */
  textBottom: number;
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

  // Build mirrored content with a zero-size sentinel at the caret offset ──
  m.textContent = "";
  m.appendChild(document.createTextNode(el.value.substring(0, pos)));

  const marker = document.createElement("span");
  // inline-block + 0×0 so it takes no layout space (wrapping matches the real element
  // exactly) while still being a `vertical-align` target, unlike a zero-width character.
  Object.assign(marker.style, { display: "inline-block", width: "0px", height: "0px", verticalAlign: "text-bottom" });
  m.appendChild(marker);

  m.appendChild(document.createTextNode(el.value.substring(pos)));

  // Measure ───────────────────────────────────────────────────────────────
  const markerRect = marker.getBoundingClientRect(); // a point: top === bottom
  const mirrorRect = m.getBoundingClientRect();
  const elRect = el.getBoundingClientRect();

  const contentX = markerRect.left - mirrorRect.left;
  const contentY = markerRect.top - mirrorRect.top;

  const borderTop = parseFloat(computed.borderTopWidth) || 0;
  const borderLeft = parseFloat(computed.borderLeftWidth) || 0;

  const metrics: CaretMetrics = {
    left: elRect.left + borderLeft + contentX - el.scrollLeft,
    textBottom: elRect.top + borderTop + contentY - el.scrollTop,
  };

  // Keep the mirror element alive for reuse; just clear its content.
  m.textContent = "";

  return metrics;
}
