// @vitest-environment jsdom
import { PerspectiveCamera } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CameraRig } from "./CameraRig";

afterEach(() => vi.restoreAllMocks());

describe("CameraRig.dispose", () => {
  it("removes the controls' document keydown listener even after React detached the canvas", () => {
    const add = vi.spyOn(document, "addEventListener");
    const remove = vi.spyOn(document, "removeEventListener");
    const container = document.createElement("div");
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);
    document.body.appendChild(container);
    const rig = new CameraRig(new PerspectiveCamera(), canvas, [-5, -5, 5, 5], () => {});
    const keydown = add.mock.calls.find(([type]) => type === "keydown")?.[1];
    expect(keydown).toBeDefined();
    remove.mockClear(); // OrbitControls connects twice while it is constructed
    // React removes the DOM before effect cleanups run, so dispose() sees a detached canvas.
    container.remove();
    rig.dispose();
    expect(remove.mock.calls.some(([type, fn]) => type === "keydown" && fn === keydown)).toBe(true);
  });
});
