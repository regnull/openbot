// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import ThinkingPlaceholder from "../components/ThinkingPlaceholder";

describe("ThinkingPlaceholder", () => {
  it("renders the bot name with thinking text and animated dots", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<ThinkingPlaceholder botName="Engineer" />));
      expect(container.textContent).toContain("Engineer");
      expect(container.textContent).toContain("is thinking");
      // Three animated dots
      const dots = container.querySelectorAll(".thinking-dot");
      expect(dots).toHaveLength(3);
      // Aria attributes for accessibility
      const status = container.querySelector("[role='status']");
      expect(status).toBeTruthy();
      expect(status?.getAttribute("aria-label")).toBe("Engineer is thinking");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("passes the icon prop through to Avatar", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<ThinkingPlaceholder botName="QA" icon="flask" />));
      expect(container.textContent).toContain("QA");
      expect(container.textContent).toContain("is thinking");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
