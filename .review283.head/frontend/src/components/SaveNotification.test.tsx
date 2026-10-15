// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SaveNotification from "./SaveNotification";
import { dismissSaveNotification, notifySave } from "../lib/saveNotifications";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let el: HTMLDivElement;
beforeEach(async () => {
  vi.useFakeTimers();
  dismissSaveNotification();
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
  await act(async () => { root.render(<StrictMode><SaveNotification /></StrictMode>); });
});
afterEach(async () => {
  await act(async () => root.unmount());
  el.remove(); dismissSaveNotification(); vi.useRealTimers();
});

describe("save notification", () => {
  it("announces politely, deduplicates, and automatically dismisses without stealing focus", async () => {
    const status = el.querySelector('[role="status"]')!;
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toBe("");
    const before = document.activeElement;
    await act(async () => { notifySave("Settings saved"); notifySave("Settings saved"); });
    expect(el.querySelectorAll("button")).toHaveLength(1);
    expect(document.activeElement).toBe(before);
    await act(async () => vi.advanceTimersByTime(4000));
    await act(async () => notifySave("Settings saved"));
    await act(async () => vi.advanceTimersByTime(1000));
    expect(status.textContent).toBe("");
  });

  it("pauses dismissal for keyboard focus and supports manual dismissal", async () => {
    await act(async () => notifySave("Settings saved"));
    const close = el.querySelector("button")!;
    await act(async () => close.focus());
    await act(async () => vi.advanceTimersByTime(10000));
    expect(el.textContent).toContain("Settings saved");
    await act(async () => close.blur());
    await act(async () => vi.advanceTimersByTime(5000));
    expect(el.textContent).toBe("");
    await act(async () => notifySave("Bot settings saved"));
    await act(async () => el.querySelector("button")!.click());
    expect(el.textContent).toBe("");
  });

  it("replaces previous feedback and gives the new message its own lifetime", async () => {
    await act(async () => notifySave("Settings saved"));
    await act(async () => vi.advanceTimersByTime(4000));
    await act(async () => notifySave("Could not save changes.", "error"));
    await act(async () => vi.advanceTimersByTime(1000));
    expect(el.textContent).not.toContain("Settings saved");
    expect(el.textContent).toContain("Could not save changes.");
    await act(async () => vi.advanceTimersByTime(4000));
    expect(el.textContent).toBe("");
  });
});
