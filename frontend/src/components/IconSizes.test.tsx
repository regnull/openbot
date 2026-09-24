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

describe("icon sizes — ~30% bump", () => {
  describe("BotIcon", () => {
    it("renders at 48×48 (h-12 w-12) by default (+33% from h-9)", () => {
      const { firstChild } = render(<BotIcon icon="🤖" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-12");
      expect(span.className).toContain("w-12");
      expect(span.className).toContain("text-xl");
    });

    it("allows caller to override dimensions via className", () => {
      const { firstChild } = render(<BotIcon icon="🤖" className="h-8 w-8 text-base" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-8");
      expect(span.className).toContain("w-8");
    });

    it("supports an unenclosed presentation for navbar icons", () => {
      const { firstChild } = render(<BotIcon icon="🤖" bare />);
      const span = firstChild as HTMLElement;
      expect(span.className).not.toContain("border");
      expect(span.className).not.toContain("bg-sunken");
      expect(span.className).not.toContain("rounded-ui");
      expect(span.getAttribute("aria-label")).toBeTruthy();
      expect(span.getAttribute("title")).toBeTruthy();
    });
  });

  describe("Avatar", () => {
    it.each(["human", "user"])("renders a labeled user icon for %s participants instead of initials", (kind) => {
      const { firstChild } = render(<Avatar name="You" kind={kind} />);
      const avatar = firstChild as HTMLElement;
      expect(avatar.getAttribute("aria-label")).toBe("You");
      expect(avatar.getAttribute("title")).toBe("You");
      expect(avatar.querySelector("svg")).toBeTruthy();
      expect(avatar.textContent).not.toContain("YO");
    });

    it("renders at 48×48 (h-12 w-12) by default (+20% from h-10)", () => {
      const { firstChild } = render(<Avatar name="Alice" kind="bot" />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-12");
      expect(span.className).toContain("w-12");
      expect(span.className).toContain("text-base");
    });

    it("renders at 40×40 (h-10 w-10) in small mode (+25% from h-8)", () => {
      const { firstChild } = render(<Avatar name="Alice" kind="bot" small />);
      const span = firstChild as HTMLElement;
      expect(span.className).toContain("h-10");
      expect(span.className).toContain("w-10");
      expect(span.className).toContain("text-sm");
    });
  });
});
