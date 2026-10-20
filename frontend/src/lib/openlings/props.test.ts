import { describe, expect, it } from "vitest";
import { CLIP_IDS, clipInfo, crossfadeSeconds, returnClip } from "./animations";
import { Quaternion, Vector3 } from "three";
import { NOTCH_L, NOTCH_R, PROPS, PROP_IDS, blendGrip, buildLoadout, conflicts, placeProp, type PropId } from "./props";
import { ROLES } from "./roles";

describe("Openling props", () => {
  it("lists the 13 props of the design sheet, each with a unique GLB node", () => {
    expect(PROP_IDS).toHaveLength(13);
    expect(new Set(PROP_IDS.map((id) => PROPS[id].node)).size).toBe(13);
    for (const id of PROP_IDS) {
      expect(PROPS[id].placements[PROPS[id].defaultPlacement]).toBeDefined();
    }
  });

  it("uses unit quaternions for every offset", () => {
    for (const id of PROP_IDS) {
      for (const a of Object.values(PROPS[id].placements)) {
        const q = a?.offset?.quaternion;
        if (q) expect(Math.hypot(...q)).toBeCloseTo(1, 3);
      }
    }
  });

  it("keeps one pair of eyewear: goggles replace glasses", () => {
    let l = placeProp({}, "square_glasses", "worn").loadout;
    const change = placeProp(l, "research_goggles", "worn");
    l = change.loadout;
    expect(l).toEqual({ research_goggles: "worn" });
    expect(change.removed.map((r) => r.id)).toEqual(["square_glasses"]);
    expect(placeProp(l, "round_glasses", "worn").loadout).toEqual({ round_glasses: "worn" });
  });

  it("does not allow the cap and the large headphones together", () => {
    expect(conflicts("cap", "large_headphones")).toBe(true);
    const l = placeProp({ cap: "worn" }, "large_headphones", "worn");
    expect(l.loadout).toEqual({ large_headphones: "worn" });
    expect(l.removed[0].id).toBe("cap");
  });

  it("holds one prop per hand", () => {
    let l = placeProp({}, "tablet", "heldLeft").loadout;
    l = placeProp(l, "pen", "heldRight").loadout;
    const change = placeProp(l, "smartphone", "heldLeft");
    expect(change.loadout).toEqual({ pen: "heldRight", smartphone: "heldLeft" });
    expect(change.removed).toEqual([{ id: "tablet", reason: expect.stringContaining("left hand") }]);
    // moving a prop to the other hand frees its old hand
    expect(placeProp(change.loadout, "pen", "heldLeft").loadout).toEqual({ pen: "heldLeft" });
  });

  it("rejects placements a prop does not support and removes props with hidden", () => {
    expect(() => placeProp({}, "laptop", "heldLeft")).toThrow();
    expect(() => placeProp({}, "cap", "desk")).toThrow();
    expect(placeProp({ cap: "worn" }, "cap", "hidden").loadout).toEqual({});
  });

  it("seats every carry grip in the mitten's thumb/palm notch, not on the outside of the hand", () => {
    // Prop bounds in their own frame (openling-props-v01.glb), grown by 6 mm for the crease surface.
    const bounds: Partial<Record<PropId, [number[], number[]]>> = {
      smartphone: [[-0.037, -0.075, -0.011], [0.04, 0.075, 0.011]],
      paper_notebook: [[-0.073, -0.087, -0.014], [0.069, 0.087, 0.016]],
      tablet: [[-0.102, -0.075, -0.009], [0.102, 0.075, 0.011]],
      pen: [[-0.008, -0.035, -0.014], [0.008, 0.094, 0.008]],
      wrench: [[-0.031, -0.094, -0.008], [0.031, 0.108, 0.008]],
    };
    for (const [id, [lo, hi]] of Object.entries(bounds) as [PropId, [number[], number[]]][]) {
      for (const hand of ["heldLeft", "heldRight"] as const) {
        const grip = PROPS[id].placements[hand]!.offset!;
        const notch = new Vector3(...(hand === "heldLeft" ? NOTCH_L : NOTCH_R));
        const local = notch.sub(new Vector3(...grip.position!)).applyQuaternion(new Quaternion(...grip.quaternion!).invert());
        local.toArray().forEach((v, i) => {
          expect(v, `${id} ${hand} axis ${i}`).toBeGreaterThan(lo[i] - 0.006);
          expect(v, `${id} ${hand} axis ${i}`).toBeLessThan(hi[i] + 0.006);
        });
      }
    }
  });

  it("lets several desk props share the desk at their own spots", () => {
    const l = buildLoadout([{ id: "laptop", placement: "desk" }, { id: "tablet", placement: "desk" }, { id: "smartphone", placement: "desk" }]);
    expect(Object.keys(l).sort()).toEqual(["laptop", "smartphone", "tablet"]);
  });
});

describe("Openling held-prop grips", () => {
  const tablet = PROPS.tablet.placements.heldLeft!;
  it("uses the carry grip outside its special clips and the clip grip inside", () => {
    expect(blendGrip(tablet, { Idle: 1 }).position).toEqual(tablet.offset!.position);
    expect(blendGrip(tablet, { Reporting: 1 }).position).toEqual(tablet.clipOffsets!.Reporting!.position);
    expect(blendGrip(tablet, {}).quaternion).toEqual(tablet.offset!.quaternion);
  });

  it("blends grips by crossfade weight without leaving the unit sphere", () => {
    const a = tablet.offset!.position!, b = tablet.clipOffsets!.Reporting!.position!;
    const mid = blendGrip(tablet, { Idle: 0.5, Reporting: 0.5 });
    for (let i = 0; i < 3; i++) expect(mid.position[i]).toBeCloseTo((a[i] + b[i]) / 2, 6);
    expect(Math.hypot(...mid.quaternion)).toBeCloseTo(1, 9);
  });
});

describe("Openling roles", () => {
  it("defines the six roles with valid, conflict-free loadouts", () => {
    expect(ROLES.map((r) => r.id)).toEqual(["commander", "coder", "researcher", "tester", "ops", "reporter"]);
    for (const role of ROLES) {
      expect(CLIP_IDS).toContain(role.clip);
      const loadout = buildLoadout(role.props);
      expect(Object.keys(loadout)).toHaveLength(role.props.length); // nothing knocked off
      for (const p of role.props) expect(PROPS[p.id].placements[p.placement]).toBeDefined();
    }
  });
});

describe("Openling clips", () => {
  it("returns one-shots to the loop that was playing", () => {
    expect(clipInfo("Wave").loop).toBe(false);
    expect(returnClip("Wave", "Reporting")).toBe("Reporting");
    expect(returnClip("Wave", null)).toBe("Idle");
    expect(returnClip("Wave", "Wave")).toBe("Idle");
  });

  it("fades longer when sitting down or standing up", () => {
    expect(crossfadeSeconds(null, "Idle")).toBe(0);
    expect(crossfadeSeconds("Idle", "Walk")).toBeLessThan(crossfadeSeconds("Idle", "SitIdle"));
    expect(crossfadeSeconds("Typing", "SitIdle")).toBe(crossfadeSeconds("Idle", "Walk"));
  });
});
