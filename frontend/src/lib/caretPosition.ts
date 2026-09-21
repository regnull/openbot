/**
 * Measures the pixel position of the caret (cursor) inside an `<input>` or
 * `<textarea>` using a hidden mirror-element technique.
 *
 * `<textarea>` lays its text out top-down, one line at a time, exactly like
 * any other block: the mirror copies its computed styles and text, inserts a
 * zero-size sentinel at the caret offset, and the sentinel's bounding rect
 * gives the same "text-bottom" reference line an inline element like the
 * `.caret` cursor aligns itself to (see index.css) -- not the top or the
 * full height of the surrounding line box, which is usually taller once a
 * line-height beyond the font's own metrics is applied (e.g. this app's
 * `leading-relaxed` composer). Anchoring a short cursor at the line box's
 * top left it floating visibly above the text; anchoring at this point
 * instead puts it exactly where `.caret` would render inline.
 *
 * `<input>`, in every mainstream browser, instead vertically *centers* its
 * one line of text within its padding box, regardless of `line-height` --
 * this is intrinsic control rendering, not something a cloned CSS block on a
 * mirror `<div>` reproduces. A fixed-height `Input` (this app's `h-9`, no
 * vertical padding) genuinely centers a short line inside a much taller box;
 * measuring it as if it were top-anchored, like a textarea, put the cursor
 * near the top of that box instead of centered in it. So for `<input>` this
 * returns the vertical *center* of its content box instead, derived from
 * the element's own geometry rather than the mirror.
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
  /** Where to vertically anchor a cursor of a given height at this caret, and how:
   * `{kind: "bottom", y}` -- align the cursor's own bottom edge with `y` (a `<textarea>`'s
   * "text-bottom" reference, the same one `vertical-align: text-bottom` uses).
   * `{kind: "center", y}` -- center the cursor on `y` (an `<input>`'s content-box center,
   * matching how the browser itself centers the input's one line of text). */
  align: { kind: "bottom" | "center"; y: number };
}

/** Vertical center of `el`'s content box (border and padding excluded either side), in
 * viewport coordinates -- where a browser centers an `<input>`'s one line of text. Takes the
 * border widths already parsed by the caller rather than re-reading `computed` for them, since
 * this runs on every animation frame while an `<input>` is focused. */
function centerY(elRect: DOMRect, computed: CSSStyleDeclaration, borderTop: number, borderBottom: number): number {
  const paddingTop = parseFloat(computed.paddingTop) || 0;
  const paddingBottom = parseFloat(computed.paddingBottom) || 0;
  const contentTop = elRect.top + borderTop + paddingTop;
  const contentHeight = elRect.height - borderTop - borderBottom - paddingTop - paddingBottom;
  return contentTop + contentHeight / 2;
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
  const borderBottom = parseFloat(computed.borderBottomWidth) || 0;
  const borderLeft = parseFloat(computed.borderLeftWidth) || 0;

  const left = elRect.left + borderLeft + contentX - el.scrollLeft;
  const align: CaretMetrics["align"] = isTextarea
    ? { kind: "bottom", y: elRect.top + borderTop + contentY - el.scrollTop }
    : { kind: "center", y: centerY(elRect, computed, borderTop, borderBottom) };
  const metrics: CaretMetrics = { left, align };

  // Keep the mirror element alive for reuse; just clear its content.
  m.textContent = "";

  return metrics;
}
