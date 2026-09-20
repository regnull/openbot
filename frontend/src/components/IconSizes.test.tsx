// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import BotIcon from "./BotIcon";
import Avatar from "./Avatar";

function render(el: React.ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  act(() => { createRoot(container).render(el); });
  return container;
}

describe("icon sizes — 25% bump", () => {
  describe("BotIcon", () => {
    it("renders at 36×36 (h-9 w-9) by default", () => {
      const { firstChild } = render(<BotIcon icon="🤖" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-9");
      expect(span.className).toContain("w-9");
      expect(span.className).toContain("text-lg");
    });

    it("allows caller to override dimensions via className", () => {
      const { firstChild } = render(<BotIcon icon="🤖" className="h-8 w-8 text-base" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-8");
      expect(span.className).toContain("w-8");
    });
  });

  describe("Avatar", () => {
    it("renders at 40×40 (h-10 w-10) by default", () => {
      const { firstChild } = render(<Avatar name="Alice" kind="bot" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-10");
      expect(span.className).toContain("w-10");
      expect(span.className).toContain("text-sm");
    });

    it("renders at 32×32 (h-8 w-8) in small mode", () => {
      const { firstChild } = render(<Avatar name="Alice" kind="bot" small />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-8");
      expect(span.className).toContain("w-8");
      expect(span.className).toContain("text-xs");
    });
  });
});
