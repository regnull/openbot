// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NewThreadControl from "./NewThreadControl";
import { Api } from "../api/client";

vi.mock("../api/client", () => ({ Api: { createThread: vi.fn() } }));

function renderControl() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const locations: string[] = [];
  function Probe() {
    const location = useLocation();
    locations.push(location.pathname);
    return <NewThreadControl />;
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => { root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/inbox"]}><Probe /></MemoryRouter></QueryClientProvider>); });
  return { container, root, locations };
}

async function flush() { await act(async () => { await Promise.resolve(); }); }

afterEach(() => { vi.clearAllMocks(); document.body.replaceChildren(); });

describe("NewThreadControl", () => {
  it("creates and opens a default thread from the main button", async () => {
    vi.mocked(Api.createThread).mockResolvedValue({ id: "thread-1" } as never);
    const view = renderControl();
    await act(async () => { (view.container.querySelector('button[aria-label="New thread"]') as HTMLButtonElement).click(); });
    await flush();
    expect(Api.createThread).toHaveBeenCalledWith({ handles: [] });
    expect(view.locations.at(-1)).toBe("/threads/thread-1");
    view.root.unmount();
  });

  it("keeps the expand action separate and exposes exactly the two requested options", async () => {
    const view = renderControl();
    const buttons = [...view.container.querySelectorAll("button")];
    expect(buttons).toHaveLength(2);
    expect(buttons[1].getAttribute("aria-label")).toBe("New thread options");
    await act(async () => { buttons[1].dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const menuItems = [...view.container.querySelectorAll('[role="menuitem"]')];
    expect(menuItems.map((item) => item.textContent?.trim())).toEqual(["Start thread", "Set up thread"]);
    view.root.unmount();
  });

  it("uses the same default creation for Start thread and opens setup for Set up thread", async () => {
    vi.mocked(Api.createThread).mockResolvedValue({ id: "thread-2" } as never);
    const view = renderControl();
    const expand = () => act(async () => { (view.container.querySelector('button[aria-label="New thread options"]') as HTMLButtonElement).click(); });
    await expand();
    await act(async () => { view.container.querySelector('[role="menuitem"]')!.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await flush();
    expect(Api.createThread).toHaveBeenCalledWith({ handles: [] });
    expect(view.locations.at(-1)).toBe("/threads/thread-2");
    await expand();
    await act(async () => { view.container.querySelectorAll('[role="menuitem"]')[1].dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(view.locations.at(-1)).toBe("/threads");
    view.root.unmount();
  });
});
