import { Box3, Mesh, Vector3, type Material, type Object3D, type Skeleton, type SkinnedMesh, type Texture } from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";
import { facingAzimuthDeg } from "../../../lib/openlings/cameraViews";

/** The approved static lookdev asset (Phase 0B-W visual baseline). */
export const BASE_OPENLING_URL = "/models/openlings/base-openling-lookdev-v01.glb";
/** The same character, rigged: skeleton, six clips, expression morphs and prop sockets. */
export const ANIMATED_OPENLING_URL = "/models/openlings/base-openling-animated-v01.glb";
/** All 13 props, one root node each. */
export const OPENLING_PROPS_URL = "/models/openlings/openling-props-v01.glb";

/** Parsed GLBs, shared by every viewer so remounting never re-downloads or re-parses the asset. */
const cache = new Map<string, Promise<GLTF>>();
const progressListeners = new Map<string, Set<(fraction: number) => void>>();
const byteLengths = new Map<string, number>();

/** Download size of a loaded GLB, when the server reported it. */
export function gltfByteLength(url: string): number | null {
  return byteLengths.get(url) ?? null;
}

export function loadGltf(url: string, onProgress?: (fraction: number) => void): Promise<GLTF> {
  let pending = cache.get(url);
  if (!pending) {
    progressListeners.set(url, new Set());
    // The GLBs are compressed with EXT_meshopt_compression (lossless: no quantization, no filters).
    pending = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(url, (e) => {
      if (!e.lengthComputable) return;
      byteLengths.set(url, e.total);
      progressListeners.get(url)?.forEach((fn) => fn(e.loaded / e.total));
    });
    // A failed download must not poison the cache: the next attempt retries.
    pending.catch(() => cache.delete(url)).finally(() => progressListeners.delete(url));
    cache.set(url, pending);
  }
  // Only an in-flight download reports progress. A listener added to a settled one would never be
  // released, and it keeps its whole viewer alive after unmount.
  if (onProgress) progressListeners.get(url)?.add(onProgress);
  return pending;
}

export interface OpenlingStats {
  meshes: number;
  vertices: number;
  triangles: number;
  materials: string[];
  textures: number;
  /** World-space bounds of the character, metres. */
  size: { x: number; y: number; z: number };
  minY: number;
  /** Direction the character faces, degrees about +Y from +Z, measured from its eyes; null if unknown. */
  facingDeg: number | null;
}

/**
 * GLTFLoader gives every primitive of a skinned mesh its own Skeleton (here 11, all over
 * the same bones and inverse bind matrices), and each one keeps its own bone texture and
 * is recomputed every frame. One shared Skeleton per instance does that work once.
 */
function shareSkeleton(root: Object3D) {
  const meshes: SkinnedMesh[] = [];
  root.traverse((o) => { if ((o as SkinnedMesh).isSkinnedMesh) meshes.push(o as SkinnedMesh); });
  const first = meshes[0]?.skeleton;
  if (!first) return;
  for (const m of meshes.slice(1)) {
    const s = m.skeleton;
    const same = s.bones.length === first.bones.length
      && s.bones.every((b, i) => b === first.bones[i] && s.boneInverses[i].equals(first.boneInverses[i]));
    if (same) m.skeleton = first;
  }
}

/**
 * Detaches a renderer that is about to be disposed from every geometry, material and texture under
 * `root`, including the cached GLTF ones shared by every viewer: a renderer listens for their "dispose"
 * event, and those listeners would otherwise keep the dead renderer alive. CPU-side data stays; the
 * next renderer uploads it again.
 */
export function releaseGpuResources(root: Object3D) {
  const resources = new Set<{ dispose(): void }>();
  root.traverse((o) => {
    const { geometry, material } = o as Partial<Mesh>;
    if (geometry) resources.add(geometry);
    if (!material) return;
    for (const m of [material].flat() as Material[]) {
      resources.add(m);
      for (const value of Object.values(m)) if ((value as Texture | null)?.isTexture) resources.add(value as Texture);
    }
  });
  resources.forEach((r) => r.dispose());
}

/** Frees per-instance GPU data of an instance made by instantiateOpenling (bone textures). */
export function disposeInstance(root: Object3D) {
  const skeletons = new Set<Skeleton>();
  root.traverse((o) => { if ((o as SkinnedMesh).isSkinnedMesh) skeletons.add((o as SkinnedMesh).skeleton); });
  skeletons.forEach((s) => s.dispose());
}

/**
 * A per-viewer instance of the shared asset: the node tree is cloned, geometry/materials/textures are shared.
 * Skinned assets are cloned with their own skeleton (SkeletonUtils), so every instance poses independently.
 */
export function instantiateOpenling(gltf: GLTF, maxAnisotropy = 1): { root: Object3D; stats: OpenlingStats } {
  let skinned = false;
  gltf.scene.traverse((o) => { if ((o as { isSkinnedMesh?: boolean }).isSkinnedMesh) skinned = true; });
  const root = skinned ? cloneSkinned(gltf.scene) : gltf.scene.clone(true);
  if (skinned) shareSkeleton(root);
  root.updateMatrixWorld(true);
  const materials = new Set<Material>();
  const textures = new Set<unknown>();
  let meshes = 0, vertices = 0, triangles = 0;
  const eyes = new Box3();
  root.traverse((o) => {
    if (!(o instanceof Mesh)) return;
    o.castShadow = o.receiveShadow = true;
    // Bounds of a posed skinned mesh are not the bind-pose bounds; never cull the character.
    if (skinned) o.frustumCulled = false;
    meshes++;
    const g = o.geometry;
    vertices += g.getAttribute("position").count;
    triangles += (g.index ? g.index.count : g.getAttribute("position").count) / 3;
    for (const m of [o.material].flat() as Material[]) {
      materials.add(m);
      for (const value of Object.values(m)) {
        if (!(value as Texture | null)?.isTexture) continue;
        const texture = value as Texture;
        textures.add(texture.source);
        // Keeps the baked fabric grain readable on surfaces seen at grazing angles (sleeves, sides).
        if (texture.anisotropy < Math.min(8, maxAnisotropy)) { texture.anisotropy = Math.min(8, maxAnisotropy); texture.needsUpdate = true; }
      }
      if (/eye/i.test(m.name)) eyes.expandByObject(o);
    }
  });
  const bounds = new Box3().setFromObject(root);
  const size = bounds.getSize(new Vector3());
  const center = bounds.getCenter(new Vector3());
  const eyeCenter = eyes.isEmpty() ? null : eyes.getCenter(new Vector3());
  return {
    root,
    stats: {
      meshes,
      vertices,
      triangles,
      materials: [...materials].map((m) => m.name).sort(),
      textures: textures.size,
      size: { x: size.x, y: size.y, z: size.z },
      minY: bounds.min.y,
      facingDeg: eyeCenter ? facingAzimuthDeg(eyeCenter.x - center.x, eyeCenter.z - center.z) : null,
    },
  };
}
