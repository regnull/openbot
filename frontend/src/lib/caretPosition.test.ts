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
  /** jsdom has no layout engine: getBoundingClientRect always reports zeros. Stubbing it is the
   * only way to exercise the actual box-geometry math (the <input> centering formula). */
  const stubRect = (el: HTMLElement, rect: Partial<DOMRect>) =>
    vi.spyOn(el, "getBoundingClientRect").mockReturnValue({
      top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...rect,
    } as DOMRect);

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

  it("returns left/align for an ordinary focused element", () => {
    const el = make("textarea", "hello world", 5);
    const m = getCaretMetrics(el);
    expect(m).not.toBeNull();
    expect(typeof m!.left).toBe("number");
    expect(typeof m!.align.y).toBe("number");
  });

  it("anchors a <textarea> to its text-bottom (top-down block flow), not a box center", () => {
    // A <textarea> lays text out like any other block, so there is no "box" to center in --
    // it must use the mirror's text-bottom reference, the same one .caret aligns to inline.
    const el = make("textarea", "hello world", 5);
    expect(getCaretMetrics(el)!.align.kind).toBe("bottom");
  });

  it("centers an <input>'s caret vertically in its content box, unlike a <textarea>", () => {
    // <input> vertically centers its one line of text within its padding box regardless of
    // line-height, in every mainstream browser -- a fixed-height Input (this app's h-9, no
    // vertical padding) genuinely centers a short line inside a much taller box. Measuring it
    // as top-anchored, like a <textarea>, put the cursor near the top of that box instead.
    const el = make("input", "hello", 5) as HTMLInputElement;
    Object.assign(el.style, { borderTopWidth: "2px", borderBottomWidth: "2px", paddingTop: "3px", paddingBottom: "5px" });
    const rectSpy = stubRect(el, { top: 100, height: 36 });
    const m = getCaretMetrics(el);
    rectSpy.mockRestore();
    expect(m!.align.kind).toBe("center");
    // contentTop = 100 + border(2) + padding(3) = 105; contentHeight = 36 - 2 - 2 - 3 - 5 = 24;
    // center = 105 + 24/2 = 117.
    expect(m!.align.y).toBe(117);
  });

  it("matches the textarea padding-box width and wrapping styles in the mirror", () => {
    const el = make("textarea", "a long wrapped line", 10);
    Object.assign(el.style, {
      width: "220px",
      borderLeftWidth: "2px",
      borderRightWidth: "3px",
      boxSizing: "border-box",
      overflowWrap: "anywhere",
      wordBreak: "break-word",
    });
    Object.defineProperty(el, "clientWidth", { configurable: true, value: 215 });

    getCaretMetrics(el);
    const mirror = document.body.querySelector<HTMLDivElement>('div[aria-hidden="true"]');
    expect(mirror).not.toBeNull();
    // The mirror is intentionally borderless and border-box sized. clientWidth
    // is already the target's padding-box width, so its effective inner width
    // must remain exactly 215px rather than becoming wider due to target borders.
    expect(mirror!.style.width).toBe("215px");
    expect(mirror!.style.borderLeftWidth).toBe("");
    expect(mirror!.style.borderRightWidth).toBe("");
    expect(parseFloat(mirror!.style.width) - parseFloat(mirror!.style.borderLeftWidth || "0") - parseFloat(mirror!.style.borderRightWidth || "0")).toBe(215);
    expect(mirror!.style.overflowWrap).toBe("anywhere");
    expect(mirror!.style.wordBreak).toBe("break-word");
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
