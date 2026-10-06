// @vitest-environment jsdom
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import ThreadOdometer from "./ThreadOdometer";

describe("ThreadOdometer", () => {
  it("renders segmented digits with an accessible label", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    act(() => { root.render(<ThreadOdometer label="in" value={12345} suffix=" tok" />); });

    expect(container.textContent).toContain("in12,345 tok");
    expect(container.querySelectorAll(".thread-odometer-digit")).toHaveLength(5);
    expect(container.firstElementChild?.getAttribute("aria-label")).toBe("in: 12,345 tok");

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
