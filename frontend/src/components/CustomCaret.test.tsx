// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import CustomCaret from "./CustomCaret";
import type { CaretMetrics } from "../lib/caretPosition";

// jsdom has no real layout engine: getBoundingClientRect always reports zeros, so any test of the
// actual positioning math needs getCaretMetrics under our control instead of the real mirror-element
// measurement (covered separately, and only for its own logic, in caretPosition.test.ts).
const mocks = vi.hoisted(() => ({ getCaretMetrics: vi.fn<(el: unknown) => CaretMetrics | null>() }));
vi.mock("../lib/caretPosition", () => ({ getCaretMetrics: mocks.getCaretMetrics }));
const { getCaretMetrics } = mocks;

describe("CustomCaret", () => {
  let root: Root;
  let el: HTMLDivElement;
  let input: HTMLInputElement;
  let restoreOffsetHeight: (() => void) | null = null;

  const overlay = () => document.body.querySelector<HTMLDivElement>(":scope > div.caret");
  const focus = async (target: HTMLElement, event: "focusin" | "focusout") => {
    act(() => target.dispatchEvent(new FocusEvent(event, { bubbles: true })));
    await act(async () => { await new Promise((r) => requestAnimationFrame(r)); });
  };
  /** One more turn of the overlay's own rAF loop, with no synthetic DOM event in between --
   * the loop must keep repositioning on its own, the way it has to for a React-cleared value. */
  const nextFrame = async () => { await act(async () => { await new Promise((r) => requestAnimationFrame(r)); }); };
  /** jsdom's real offsetHeight getter always returns 0; the alignment math needs a stand-in. */
  const stubOverlayOffsetHeight = (px: number) => {
    restoreOffsetHeight?.();
    const proto = HTMLElement.prototype;
    const original = Object.getOwnPropertyDescriptor(proto, "offsetHeight");
    Object.defineProperty(proto, "offsetHeight", { configurable: true, get: () => px });
    restoreOffsetHeight = () => { if (original) Object.defineProperty(proto, "offsetHeight", original); };
  };

  beforeEach(async () => {
    getCaretMetrics.mockReset();
    el = document.createElement("div");
    document.body.appendChild(el);
    root = createRoot(el);
    input = document.createElement("input");
    input.style.fontSize = "20px";
    document.body.appendChild(input);
    await act(async () => { root.render(<CustomCaret />); });
  });

  afterEach(() => {
    act(() => root.unmount());
    el.remove();
    input.remove();
    document.querySelector(".caret")?.remove();
    restoreOffsetHeight?.();
    restoreOffsetHeight = null;
  });

  it("uses the shared .caret class, not a bespoke input-only style", async () => {
    getCaretMetrics.mockReturnValue({ left: 20, align: { kind: "bottom", y: 40 } });
    await focus(input, "focusin");
    const caret = overlay();
    expect(caret).not.toBeNull();
    expect(caret!.className).toBe("caret");
    // Everything visual (size, color, the pulse animation, reduced-motion handling) comes from
    // that one class and its own CSS -- no leftover per-instance overrides, so this reads as the
    // exact same cursor as RunCard's decorative streaming one, not a similar-looking cousin.
    expect(caret!.style.animation).toBe("");
    expect(caret!.style.backgroundColor).toBe("");
  });

  it("scales to the focused element's font size, so the shared em-based sizing matches it", async () => {
    getCaretMetrics.mockReturnValue({ left: 0, align: { kind: "bottom", y: 24 } });
    await focus(input, "focusin");
    expect(overlay()!.style.fontSize).toBe("20px");
  });

  it("hides on blur and ignores password fields", async () => {
    getCaretMetrics.mockReturnValue({ left: 0, align: { kind: "bottom", y: 24 } });
    await focus(input, "focusin");
    expect(overlay()!.style.display).toBe("");
    await focus(input, "focusout");
    expect(overlay()!.style.display).toBe("none");

    const pw = document.createElement("input");
    pw.type = "password";
    document.body.appendChild(pw);
    await focus(pw, "focusin");
    expect(overlay()!.style.display).toBe("none");
    pw.remove();
  });

  it("for a <textarea>-shaped caret ('bottom'), aligns the block's own bottom with the text-bottom reference, not the top of a taller line box", async () => {
    // `align.y` for `kind: "bottom"` is the same "text-bottom" reference `vertical-align:
    // text-bottom` uses for the inline `.caret` in RunCard (see caretPosition.ts). Anchoring the
    // overlay's *top* there -- the old, buggy behavior -- left a short block floating near the
    // top of a taller `leading-relaxed` line; anchoring its bottom there instead puts it where
    // `.caret` would actually render inline, regardless of the block's own rendered height (21,
    // here standing in for .caret's `1.05em` at this font size).
    stubOverlayOffsetHeight(21);
    getCaretMetrics.mockReturnValue({ left: 50, align: { kind: "bottom", y: 130 } });
    await focus(input, "focusin");
    expect(overlay()!.style.top).toBe(`${130 - 21}px`);
    expect(overlay()!.style.left).toBe("50px");
  });

  it("for an <input>-shaped caret ('center'), centers the block on the content-box center instead of bottom-aligning it", async () => {
    // <input> vertically centers its one line of text within its box regardless of line-height
    // (see caretPosition.ts); bottom-aligning the cursor here, as for a <textarea>, put it too
    // low relative to text that the browser had centered higher up in a tall fixed-height box
    // (e.g. the "ask human" answer box, `Input`'s `h-9`).
    stubOverlayOffsetHeight(20);
    getCaretMetrics.mockReturnValue({ left: 50, align: { kind: "center", y: 118 } });
    await focus(input, "focusin");
    expect(overlay()!.style.top).toBe(`${118 - 10}px`);
  });

  it("keeps repositioning every frame, not only on input/selectionchange -- a React-controlled value clear (e.g. the composer resetting the textarea after Enter) fires neither", async () => {
    stubOverlayOffsetHeight(21);
    getCaretMetrics.mockReturnValue({ left: 200, align: { kind: "bottom", y: 24 } }); // caret at the end of typed text
    await focus(input, "focusin");
    expect(overlay()!.style.left).toBe("200px");

    // The composer clears the textarea via React state, not a real keystroke: no "input" or
    // "selectionchange" event follows. Only the metrics function's return value changes.
    getCaretMetrics.mockReturnValue({ left: 0, align: { kind: "bottom", y: 24 } }); // caret back at the start
    await nextFrame();
    expect(overlay()!.style.left).toBe("0px");
  });
});
