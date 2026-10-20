import { describe, expect, it } from "vitest";
import { CAMERA_VIEWS, facingAzimuthDeg, lensToFovDeg, verticalFovDeg, viewAzimuthDeg, viewPosition } from "./cameraViews";

describe("Openling lab camera views", () => {
  it("matches the Blender lookdev lens", () => {
    expect(lensToFovDeg(70, 36)).toBeCloseTo(28.84, 2);
  });

  it("keeps the reference FOV on the shorter side of the viewport", () => {
    expect(verticalFovDeg(30, 1.6)).toBe(30);
    expect(verticalFovDeg(30, 1)).toBe(30);
    // Portrait: the horizontal FOV stays at 30 degrees, so the vertical one widens.
    const v = verticalFovDeg(30, 0.5);
    const horizontal = (2 * Math.atan(Math.tan((v * Math.PI) / 360) * 0.5) * 180) / Math.PI;
    expect(horizontal).toBeCloseTo(30, 6);
  });

  it("places the front camera where the Blender camera is, converted to Y-up", () => {
    const p = viewPosition(0);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(0.62, 6);
    expect(p.z).toBeCloseTo(2.75, 6);
  });

  it("swings positive azimuths to the character's left (+X)", () => {
    expect(viewPosition(viewAzimuthDeg("left")).x).toBeCloseTo(2.75, 6);
    expect(viewPosition(viewAzimuthDeg("right")).x).toBeCloseTo(-2.75, 6);
    expect(viewPosition(viewAzimuthDeg("back")).z).toBeCloseTo(-2.75, 6);
    const q = viewPosition(viewAzimuthDeg("threeQuarter"));
    expect(q.x).toBeGreaterThan(0);
    expect(q.z).toBeGreaterThan(0);
  });

  it("rotates every view with the detected facing", () => {
    const p = viewPosition(0, 90);
    expect(p.x).toBeCloseTo(2.75, 6);
    expect(p.z).toBeCloseTo(0, 6);
  });

  it("keeps the reference elevation angle when zoomed", () => {
    const near = viewPosition(0, 0, 1.375);
    expect((near.y - 0.5) / 1.375).toBeCloseTo((0.62 - 0.5) / 2.75, 6);
  });

  it("detects the facing direction from the face offset", () => {
    expect(facingAzimuthDeg(0, 0.2)).toBe(0);
    expect(facingAzimuthDeg(0.2, 0.01)).toBe(90);
    expect(facingAzimuthDeg(0, -0.2)).toBe(180);
    expect(facingAzimuthDeg(0, 0)).toBeNull();
  });

  it("offers the five reference views", () => {
    expect(CAMERA_VIEWS.map((v) => v.id)).toEqual(["front", "threeQuarter", "left", "right", "back"]);
  });
});
