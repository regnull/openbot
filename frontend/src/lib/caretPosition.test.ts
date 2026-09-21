// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { getCaretMetrics } from "./caretPosition";

describe("getCaretMetrics", () => {
  const els: HTMLElement[] = [];
  const make = (tag: "input" | "textarea", value: string, pos: number) => {
    const el = document.createElement(tag);
    el.value = value;
    document.body.appendChild(el);
    el.setSelectionRange(pos, pos);
    els.push(el);
    return el;
  };

  afterEach(() => { els.splice(0).forEach((e) => e.remove()); });

  it("returns null for password, disabled, read-only, or a non-collapsed selection", () => {
    const pw = make("input", "secret", 0) as HTMLInputElement;
    pw.type = "password";
    expect(getCaretMetrics(pw)).toBeNull();

    const disabled = make("input", "x", 0);
    disabled.disabled = true;
    expect(getCaretMetrics(disabled)).toBeNull();

    const readOnly = make("input", "x", 0);
    readOnly.readOnly = true;
    expect(getCaretMetrics(readOnly)).toBeNull();

    const selected = make("input", "hello", 0);
    selected.setSelectionRange(1, 3);
    expect(getCaretMetrics(selected)).toBeNull();
  });

  it("returns left/textBottom for an ordinary focused element", () => {
    const el = make("textarea", "hello world", 5);
    const m = getCaretMetrics(el);
    expect(m).not.toBeNull();
    expect(typeof m!.left).toBe("number");
    expect(typeof m!.textBottom).toBe("number");
  });

  it("marks the caret sentinel as a zero-size, vertical-align: text-bottom inline-block, not a zero-width character -- the same alignment mechanism the .caret class itself uses, and zero layout width so it can never shift wrapping", () => {
    // getCaretMetrics clears the mirror's children (including the marker) before returning, so
    // the marker has to be captured as it's created, not queried from the DOM afterward.
    const spans: HTMLSpanElement[] = [];
    const createElement = document.createElement.bind(document);
    const spy = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const node = createElement(tag);
      if (tag === "span") spans.push(node as HTMLSpanElement);
      return node;
    });
    const el = make("textarea", "hello world", 5);
    getCaretMetrics(el);
    spy.mockRestore();

    expect(spans).toHaveLength(1);
    const marker = spans[0];
    expect(marker.style.display).toBe("inline-block");
    expect(marker.style.width).toBe("0px");
    expect(marker.style.height).toBe("0px");
    expect(marker.style.verticalAlign).toBe("text-bottom");
    expect(marker.textContent).toBe("");
  });
});
