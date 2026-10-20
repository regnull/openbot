import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Texture } from "three";
import { describe, expect, it, vi } from "vitest";

const loads = vi.hoisted(() => [] as { onProgress: (e: { lengthComputable: boolean; loaded: number; total: number }) => void; resolve: (gltf: unknown) => void }[]);
vi.mock("three/addons/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    setMeshoptDecoder() { return this; }
    loadAsync(_url: string, onProgress: (typeof loads)[number]["onProgress"]) {
      return new Promise((resolve) => loads.push({ onProgress, resolve }));
    }
  },
}));

const { loadGltf, releaseGpuResources } = await import("./loadOpenling");

describe("loadGltf", () => {
  it("reports progress to every caller of an in-flight download and downloads once", async () => {
    const a = vi.fn(), b = vi.fn();
    const first = loadGltf("/a.glb", a);
    const second = loadGltf("/a.glb", b);
    expect(second).toBe(first);
    expect(loads).toHaveLength(1);
    loads[0].onProgress({ lengthComputable: true, loaded: 1, total: 4 });
    expect(a).toHaveBeenCalledWith(0.25);
    expect(b).toHaveBeenCalledWith(0.25);
    loads[0].resolve({ scene: new Group() });
    await first;
    // a cached load needs no listener (one registered now could never be released)
    expect(loadGltf("/a.glb", vi.fn())).toBe(first);
    expect(loads).toHaveLength(1);
  });
});

describe("releaseGpuResources", () => {
  it("disposes every geometry, material and texture once, shared ones included", () => {
    const map = new Texture();
    const material = new MeshStandardMaterial({ map });
    const geometry = new BoxGeometry();
    const root = new Group().add(new Mesh(geometry, material), new Mesh(geometry, [material, material]));
    const disposed = vi.fn();
    for (const r of [map, material, geometry]) r.addEventListener("dispose", () => disposed(r));
    releaseGpuResources(root);
    expect(disposed.mock.calls.map(([r]) => r)).toEqual(expect.arrayContaining([map, material, geometry]));
    expect(disposed).toHaveBeenCalledTimes(3);
  });
});
