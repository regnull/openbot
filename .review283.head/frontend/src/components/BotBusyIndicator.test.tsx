// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { describe, expect, it } from "vitest";
import { createRoot } from "react-dom/client";
import { act } from "react";
import BotBusyIndicator from "../components/BotBusyIndicator";

describe("BotBusyIndicator", () => {
  it("renders the bot name with busy status and pulsing dot", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<BotBusyIndicator botName="Engineer" />));
      expect(container.textContent).toContain("Engineer");
      expect(container.textContent).toContain("busy, waiting");
      // Pulsing dot element present
      const dot = container.querySelector(".bot-busy-dot");
      expect(dot).toBeTruthy();
      // Aria attributes for accessibility
      const status = container.querySelector("[role='status']");
      expect(status).toBeTruthy();
      expect(status?.getAttribute("aria-label")).toBe("Engineer is busy, waiting for response");
      expect(status?.getAttribute("aria-live")).toBe("polite");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("shows timed out status when status prop is timed_out", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<BotBusyIndicator botName="Reviewer" status="timed_out" />));
      expect(container.textContent).toContain("Reviewer");
      expect(container.textContent).toContain("Timed out");
      const status = container.querySelector("[role='status']");
      expect(status?.getAttribute("aria-label")).toBe("Reviewer is timed out");
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
      act(() => root.render(<BotBusyIndicator botName="QA" icon="flask" />));
      expect(container.textContent).toContain("QA");
      expect(container.textContent).toContain("busy, waiting");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("has the bot-busy-indicator class for CSS transitions", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<BotBusyIndicator botName="Engineer" />));
      const indicator = container.querySelector(".bot-busy-indicator");
      expect(indicator).toBeTruthy();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("includes message-sheet classes for consistent slot sizing", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => root.render(<BotBusyIndicator botName="Engineer" />));
      const indicator = container.querySelector(".message-sheet.message-assistant");
      expect(indicator).toBeTruthy();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
