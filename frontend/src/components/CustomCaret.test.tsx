// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import CustomCaret from "./CustomCaret";

describe("CustomCaret", () => {
  let root: Root;
  let el: HTMLDivElement;
  let input: HTMLInputElement;

  const overlay = () => document.body.querySelector<HTMLDivElement>(":scope > div.caret");
  const focus = async (target: HTMLElement, event: "focusin" | "focusout") => {
    act(() => target.dispatchEvent(new FocusEvent(event, { bubbles: true })));
    await act(async () => { await new Promise((r) => requestAnimationFrame(r)); });
  };

  beforeEach(async () => {
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
  });

  it("uses the shared .caret class, not a bespoke input-only style", async () => {
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
    await focus(input, "focusin");
    expect(overlay()!.style.fontSize).toBe("20px");
  });

  it("hides on blur and ignores password fields", async () => {
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
});
