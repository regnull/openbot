/**
 * The exported office GLBs and the layout manifest describe the same office: every item is a
 * node named by its id at the manifest position (same frame, no stray transforms), and the
 * screens, signs and moving parts the runtime looks up exist.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { OFFICE_GLB_URLS, OFFICE_LAYOUT } from "./layout";

interface GltfNode { name?: string; translation?: number[]; rotation?: number[]; scale?: number[]; children?: number[]; mesh?: number }
interface GltfJson {
  nodes: GltfNode[];
  scenes: { nodes: number[] }[];
  cameras?: unknown[];
  extensionsUsed?: string[];
  materials?: { name: string; alphaMode?: string }[];
}

function readGlb(url: string): GltfJson {
  const buf = readFileSync(resolve(__dirname, "../../../public", url.replace(/^\//, "")));
  const len = buf.readUInt32LE(12);
  return JSON.parse(buf.subarray(20, 20 + len).toString("utf8"));
}

const glbs = OFFICE_GLB_URLS.map(readGlb);
const nodes = new Map<string, GltfNode>();
const roots = new Set<string>();
for (const g of glbs) {
  for (const n of g.nodes) if (n.name) nodes.set(n.name, n);
  for (const i of g.scenes[0].nodes) if (g.nodes[i].name) roots.add(g.nodes[i].name!);
}

describe("office GLBs vs layout manifest", () => {
  it("contains every layout item as a root node at its manifest position and yaw", () => {
    for (const it of OFFICE_LAYOUT.items) {
      const n = nodes.get(it.id);
      expect(n, it.id).toBeDefined();
      expect(roots.has(it.id), `${it.id} is a scene root`).toBe(true);
      const [x, y, z] = n!.translation ?? [0, 0, 0];
      expect(x, `${it.id} x`).toBeCloseTo(it.position[0], 3);
      expect(y, `${it.id} y`).toBeCloseTo(it.position[1], 3);
      expect(z, `${it.id} z`).toBeCloseTo(it.position[2], 3);
      // rotation about +Y only: q = (0, sin(yaw/2), 0, cos(yaw/2))
      const [qx, qy, qz, qw] = n!.rotation ?? [0, 0, 0, 1];
      expect(Math.abs(qx) + Math.abs(qz), `${it.id} upright`).toBeLessThan(1e-4);
      const yaw = 2 * Math.atan2(qy, qw);
      const d = Math.atan2(Math.sin(yaw - it.yaw), Math.cos(yaw - it.yaw));
      expect(Math.abs(d), `${it.id} yaw`).toBeLessThan(1e-3);
      expect(n!.scale ?? [1, 1, 1]).toEqual([1, 1, 1]);
    }
  });

  it("has the signs, the moving parts and one wall node per manifest wall", () => {
    for (const s of OFFICE_LAYOUT.signs) expect(nodes.has(s.id), s.id).toBe(true);
    for (const w of OFFICE_LAYOUT.walls) expect(nodes.has(w.id), w.id).toBe(true);
    for (const j of ["Test_RobotArm_J1", "Test_RobotArm_J2", "Test_RobotArm_J3", "Test_RobotArm_J4"]) expect(nodes.has(j), j).toBe(true);
    const screens = [...nodes.keys()].filter((n) => n.startsWith("SCREEN_"));
    expect(screens.length).toBeGreaterThanOrEqual(30);
    for (const s of ["SCREEN_Ops_Wall", "SCREEN_Reporting_Screen", "SCREEN_Command_P2", "SCREEN_Desk_05_Desk_0"]) expect(screens, s).toContain(s);
  });

  it("exports no cameras, lights or preview-only objects", () => {
    for (const g of glbs) {
      expect(g.cameras ?? []).toHaveLength(0);
      expect(g.extensionsUsed ?? []).not.toContain("KHR_lights_punctual");
    }
    for (const name of nodes.keys()) expect(name, name).not.toMatch(/^(PREVIEW_|COL_|NavEdges|N_)/);
    // anchors live in the manifest, not in the GLBs
    expect(nodes.has("Lobby_Entry")).toBe(false);
  });

  it("marks glass as blended so it stays see-through", () => {
    const glass = glbs.flatMap((g) => g.materials ?? []).filter((m) => m.name === "MAT_Glass");
    expect(glass.length).toBeGreaterThan(0);
    for (const m of glass) expect(m.alphaMode).toBe("BLEND");
  });
});
