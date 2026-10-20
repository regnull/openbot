/**
 * Phase 1.1 collision regressions, checked on the real exported meshes (not the manifest footprints):
 * no plant reaches into a wall or through glass, the Ops Wall furniture does not overlap, and the
 * Openling at Ops_Desk has room (clearances measured on the posed character during the Phase 1.1 review).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Matrix4, Quaternion, Vector3 } from "three";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { describe, expect, it } from "vitest";
import { LayoutIndex, OFFICE_GLB_URLS, OFFICE_LAYOUT } from "./layout";
import { NavGraph } from "./nav";

interface GltfNode { name?: string; translation?: number[]; rotation?: number[]; scale?: number[]; children?: number[]; mesh?: number }
interface Gltf {
  nodes: GltfNode[];
  scenes: { nodes: number[] }[];
  meshes: { primitives: { attributes: Record<string, number> }[] }[];
  accessors: { bufferView: number; byteOffset?: number; count: number; componentType: number; type: string }[];
  bufferViews: { byteOffset?: number; byteLength: number; byteStride?: number; extensions?: { EXT_meshopt_compression?: MeshoptView } }[];
}
interface MeshoptView { buffer: number; byteOffset?: number; byteLength: number; byteStride: number; count: number; mode: string; filter?: string }

await MeshoptDecoder.ready;

/** The GLB's JSON and every bufferView's bytes (meshopt-compressed views decoded, as GLTFLoader does). */
function readGlb(url: string): { json: Gltf; views: Buffer[] } {
  const buf = readFileSync(resolve(__dirname, "../../../public", url.replace(/^\//, "")));
  const len = buf.readUInt32LE(12);
  const json = JSON.parse(buf.subarray(20, 20 + len).toString("utf8")) as Gltf;
  const binLen = buf.readUInt32LE(20 + len);
  const bin = buf.subarray(28 + len, 28 + len + binLen);
  const views = json.bufferViews.map((bv) => {
    const m = bv.extensions?.EXT_meshopt_compression;
    if (!m) return bin.subarray(bv.byteOffset ?? 0, (bv.byteOffset ?? 0) + bv.byteLength);
    expect(m.buffer, "meshopt data lives in the GLB binary chunk").toBe(0);
    const out = new Uint8Array(m.count * m.byteStride);
    const src = bin.subarray(m.byteOffset ?? 0, (m.byteOffset ?? 0) + m.byteLength);
    MeshoptDecoder.decodeGltfBuffer(out, m.count, m.byteStride, src, m.mode, m.filter);
    return Buffer.from(out.buffer);
  });
  return { json, views };
}

const glbs = OFFICE_GLB_URLS.map(readGlb);

/** World-space vertices of a scene-root node by name (three.js frame, as the runtime loads it). */
function worldVertices(name: string): Vector3[] {
  for (const { json, views } of glbs) {
    const rootIdx = json.scenes[0].nodes.find((i) => json.nodes[i].name === name);
    if (rootIdx === undefined) continue;
    const out: Vector3[] = [];
    const visit = (i: number, parent: Matrix4) => {
      const n = json.nodes[i];
      const m = new Matrix4().compose(
        new Vector3(...(n.translation ?? [0, 0, 0])), new Quaternion(...(n.rotation ?? [0, 0, 0, 1])), new Vector3(...(n.scale ?? [1, 1, 1])),
      );
      const world = parent.clone().multiply(m);
      if (n.mesh !== undefined) {
        for (const p of json.meshes[n.mesh].primitives) {
          const a = json.accessors[p.attributes.POSITION];
          expect(a.componentType).toBe(5126); // float
          const bv = json.bufferViews[a.bufferView];
          const view = views[a.bufferView];
          const stride = bv.byteStride ?? bv.extensions?.EXT_meshopt_compression?.byteStride ?? 12;
          const base = a.byteOffset ?? 0;
          for (let k = 0; k < a.count; k++) {
            const o = base + k * stride;
            out.push(new Vector3(view.readFloatLE(o), view.readFloatLE(o + 4), view.readFloatLE(o + 8)).applyMatrix4(world));
          }
        }
      }
      for (const c of n.children ?? []) visit(c, world);
    };
    visit(rootIdx, new Matrix4());
    return out;
  }
  throw new Error(`no node ${name}`);
}

interface Run { wall: string; a: [number, number]; u: [number, number]; n: [number, number]; len: number; hw: number; top: number }
const RUNS: Run[] = OFFICE_LAYOUT.walls.flatMap((w) => {
  const [ax, az] = w.from;
  const [bx, bz] = w.to;
  const L = Math.hypot(bx - ax, bz - az);
  const u: [number, number] = [(bx - ax) / L, (bz - az) / L];
  const cuts: [number, number][] = [];
  let t = 0;
  for (const [t0, t1] of [...w.openings].sort((p, q) => p[0] - q[0])) {
    if (t0 > t) cuts.push([t, t0]);
    t = Math.max(t, t1);
  }
  if (t < L) cuts.push([t, L]);
  const rail = Number((w as unknown as { rail?: number }).rail ?? 0);
  return cuts.map(([t0, t1]) => ({
    wall: w.id, a: [ax + u[0] * t0, az + u[1] * t0] as [number, number], u, n: [-u[1], u[0]] as [number, number], len: t1 - t0,
    hw: w.thickness / 2, top: w.height + rail,
  }));
});

/** How far an item's vertices reach past the near face of each wall (only walls it reaches into). */
function wallPenetration(itemId: string): Record<string, number> {
  const it = OFFICE_LAYOUT.items.find((i) => i.id === itemId)!;
  const [cx, , cz] = it.position;
  const out: Record<string, number> = {};
  const verts = worldVertices(itemId);
  for (const r of RUNS) {
    const side = (cx - r.a[0]) * r.n[0] + (cz - r.a[1]) * r.n[1] >= 0 ? 1 : -1;
    for (const v of verts) {
      if (v.y > r.top) continue;
      const t = (v.x - r.a[0]) * r.u[0] + (v.z - r.a[1]) * r.u[1];
      if (t < -0.02 || t > r.len + 0.02) continue;
      const d = ((v.x - r.a[0]) * r.n[0] + (v.z - r.a[1]) * r.n[1]) * side;
      if (d < r.hw) out[r.wall] = Math.max(out[r.wall] ?? 0, r.hw - d);
    }
  }
  return out;
}

function aabb(itemId: string) {
  const vs = worldVertices(itemId);
  const lo = new Vector3(Infinity, Infinity, Infinity), hi = new Vector3(-Infinity, -Infinity, -Infinity);
  for (const v of vs) { lo.min(v); hi.max(v); }
  return { lo, hi };
}

function boxGap(px: number, pz: number, b: { lo: Vector3; hi: Vector3 }) {
  return Math.hypot(Math.max(b.lo.x - px, 0, px - b.hi.x), Math.max(b.lo.z - pz, 0, pz - b.hi.z));
}

describe("office collisions (exported meshes)", () => {
  it("keeps every plant's leaves out of the walls and the glass (a leaf tip may brush a face by 2.5 cm)", () => {
    const plants = OFFICE_LAYOUT.items.filter((i) => i.type.startsWith("plant_"));
    expect(plants.length).toBeGreaterThan(20);
    const bad: string[] = [];
    for (const p of plants) {
      for (const [wall, depth] of Object.entries(wallPenetration(p.id))) if (depth > 0.025) bad.push(`${p.id} -> ${wall}: ${depth.toFixed(3)} m`);
    }
    expect(bad).toEqual([]);
  });

  it("keeps the greenery by the 'Good ideas' wall clear of it (the reported Phase 1 defect)", () => {
    for (const id of ["Front_Plant_R", "Ops_Plant_3", "Front_Planter_R"]) {
      const pen = wallPenetration(id);
      expect(pen.W_Front_R ?? 0, id).toBeLessThan(0.025);
    }
  });

  it("keeps the Ops Wall console clear of the rack, and room for the Openling at Ops_Desk", () => {
    const rack = aabb("Ops_Rack"), console_ = aabb("Ops_Console"), cabinet = aabb("Ops_Cabinet");
    const overlap = (a: typeof rack, b: typeof rack) => a.lo.x < b.hi.x && b.lo.x < a.hi.x && a.lo.z < b.hi.z && b.lo.z < a.hi.z;
    expect(overlap(rack, console_)).toBe(false);
    expect(overlap(rack, cabinet)).toBe(false);
    const desk = new LayoutIndex().anchor("Ops_Desk");
    const [x, , z] = desk.position;
    // the headphones and the wrench hand face the rack; the belly faces the console it works at
    expect(boxGap(x, z, rack)).toBeGreaterThanOrEqual(0.4);
    expect(boxGap(x, z, console_)).toBeGreaterThanOrEqual(0.3);
    expect(boxGap(x, z, cabinet)).toBeGreaterThanOrEqual(0.4);
  });

  it("reaches every Ops Wall anchor and keeps the routes around the console", () => {
    const index = new LayoutIndex();
    const nav = new NavGraph(index);
    for (const a of ["Ops_Inspect", "Ops_Desk", "Ops_AlertReview", "Ops_Exit"]) {
      for (const b of ["Ops_Inspect", "Ops_Desk", "Ops_AlertReview", "Ops_Exit"]) {
        if (a === b) continue;
        const from = index.anchor(a);
        const p: [number, number] = from.approach ? [from.approach[0], from.approach[2]] : [from.position[0], from.position[2]];
        const r = nav.route(p, b);
        expect(r, `${a} -> ${b}`).not.toBeNull();
        expect(r!.length, `${a} -> ${b}`).toBeLessThan(6);
      }
    }
    const edges = new Set(OFFICE_LAYOUT.nav.edges.map(([a, b]) => [a, b].sort().join("|")));
    expect(edges.has(["N_Ops_Rear", "Ops_AlertReview"].sort().join("|"))).toBe(true);
    expect(edges.has(["Ops_AlertReview", "Ops_Desk__approach"].sort().join("|"))).toBe(true);
  });
});
