import { describe, expect, it, vi } from "vitest";
import { isNearBottom, scrollToBottom } from "./autoScroll";

describe("isNearBottom", () => {
  it("returns true when the viewport is already at the bottom", () => {
    expect(isNearBottom({ scrollHeight: 1_000, scrollTop: 600, clientHeight: 400 })).toBe(true);
  });

  it("returns true when the viewport is within the bottom threshold", () => {
    expect(isNearBottom({ scrollHeight: 1_000, scrollTop: 525, clientHeight: 400 })).toBe(true);
  });

  it("returns false when the user has scrolled away from the bottom", () => {
    expect(isNearBottom({ scrollHeight: 1_000, scrollTop: 400, clientHeight: 400 })).toBe(false);
  });

  it("honors a custom threshold", () => {
    const metrics = { scrollHeight: 1_000, scrollTop: 525, clientHeight: 400 };
    expect(isNearBottom(metrics, 50)).toBe(false);
    expect(isNearBottom(metrics, 75)).toBe(true);
  });
});


describe("scrollToBottom", () => {
  it("scrolls to the full scroll height", () => {
    const scrollTo = vi.fn();
    const element = { scrollHeight: 1_234, scrollTo } as unknown as HTMLElement;

    scrollToBottom(element);

    expect(scrollTo).toHaveBeenCalledWith({ top: 1_234 });
  });
});
