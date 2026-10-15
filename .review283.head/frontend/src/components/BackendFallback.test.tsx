// @vitest-environment jsdom
// Wiring tests for BackendFallback: it must navigate to the default home view
// (/inbox) when `openbot:backend-unavailable` fires, and must NOT navigate when
// the user is already on /inbox (loop guard: failing home-view queries would
// otherwise re-trigger navigation forever).
import { afterEach, describe, expect, it } from "vitest";
import { useEffect } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import BackendFallback from "./BackendFallback";
import { backendUnavailableEvent } from "../api/errors";

async function until(cond: () => boolean, what: string) {
  for (let i = 0; i < 200; i++) {
    if (cond()) return;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`timed out waiting for: ${what}`);
}

/** Renders BackendFallback inside a MemoryRouter and records every location change. */
function renderAt(initialPath: string) {
  const locations: { pathname: string; key: string }[] = [];
  function Probe() {
    const loc = useLocation();
    useEffect(() => { locations.push({ pathname: loc.pathname, key: loc.key }); }, [loc]);
    return null;
  }
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  root.render(
    <MemoryRouter initialEntries={[initialPath]}>
      <BackendFallback>
        <Probe />
      </BackendFallback>
    </MemoryRouter>,
  );
  return {
    locations,
    last: () => locations[locations.length - 1],
    async settle() {
      await until(() => locations.length >= 1, "initial render");
      return locations[locations.length - 1];
    },
    fire: () => window.dispatchEvent(new CustomEvent(backendUnavailableEvent)),
    unmount: () => { root.unmount(); container.remove(); },
  };
}

let mounted: ReturnType<typeof renderAt> | undefined;
afterEach(() => mounted?.unmount());

describe("BackendFallback", () => {
  it("navigates to /inbox when the backend-unavailable event fires on another view", async () => {
    mounted = renderAt("/threads/t1");
    const before = await mounted.settle();
    expect(before.pathname).toBe("/threads/t1");

    mounted.fire();
    await until(() => mounted!.locations.length === 2, "navigation to /inbox");
    expect(mounted.last()!.pathname).toBe("/inbox");
    await new Promise((r) => setTimeout(r, 30)); // no further churn afterwards
    expect(mounted.locations).toHaveLength(2); // initial location + exactly one navigation
  });

  it("does not navigate when already on /inbox (loop guard)", async () => {
    mounted = renderAt("/inbox");
    const before = await mounted.settle();
    expect(before.pathname).toBe("/inbox");

    mounted.fire();
    mounted.fire(); // e.g. several home-view queries failing at once
    await new Promise((r) => setTimeout(r, 30));
    expect(mounted.locations).toHaveLength(1); // no navigation at all
  });

  it("does not navigate on unrelated window events", async () => {
    mounted = renderAt("/threads/t1");
    await mounted.settle();
    window.dispatchEvent(new CustomEvent("openbot:unauthorized"));
    window.dispatchEvent(new CustomEvent("some-other-event"));
    await new Promise((r) => setTimeout(r, 30));
    expect(mounted.locations).toHaveLength(1);
    expect(mounted.last()!.pathname).toBe("/threads/t1");
  });
});
