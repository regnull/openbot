// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import ThreadOdometer from "./ThreadOdometer";
import { ArrowRightIcon } from "./icons";

describe("ThreadOdometer", () => {
  it("renders segmented digits with an accessible label", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    act(() => { root.render(<ThreadOdometer label="tokens in" indicator={<ArrowRightIcon className="h-3 w-3" />} indicatorLabel="Tokens in" value={12345} unit="tok" />); });

    expect(container.textContent).toContain("12,345tok");
    expect(container.querySelector(".thread-odometer-unit")?.textContent).toBe("tok");
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelector(".thread-odometer-label")?.getAttribute("title")).toBe("Tokens in");
    expect(container.querySelectorAll(".thread-odometer-digit")).toHaveLength(5);
    expect(container.firstElementChild?.getAttribute("aria-label")).toBe("tokens in: 12,345 tok");
    expect(container.firstElementChild?.getAttribute("role")).toBe("img");

    act(() => root.unmount());
  });

  it("keeps zero values visible and represents loading accessibly", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    act(() => { root.render(<ThreadOdometer label="calls" value={0} />); });
    expect(container.textContent).toContain("calls0");
    expect(container.firstElementChild?.getAttribute("aria-label")).toBe("calls: 0");

    act(() => { root.render(<ThreadOdometer label="calls" value={42} />); });
    expect(container.firstElementChild?.getAttribute("aria-label")).toBe("calls: 42");

    act(() => { root.render(<ThreadOdometer label="calls" value={42} loading />); });
    expect(container.textContent).toContain("calls—");
    expect(container.firstElementChild?.getAttribute("aria-label")).toBe("calls: loading");

    act(() => root.unmount());
  });
});
