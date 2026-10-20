import { BufferGeometry, DoubleSide, Group, Mesh, MeshStandardMaterial, type Material, type Object3D } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import type { OfficeLayout } from "../../../lib/office/layout";

/**
 * The loaded office: static geometry merged into one mesh per material (a few dozen draw
 * calls for the whole building), plus the parts the runtime animates or paints:
 *   screens  SCREEN_* quads (UV 0..1) for CanvasTexture content
 *   signs    SIGN_* quads for signage
 *   dynamic  item roots that move (sliding chairs and stools, the robot arm joints)
 */
export interface OfficeScene {
  root: Group;
  screens: Map<string, Mesh>;
  signs: Map<string, Mesh>;
  dynamic: Map<string, Object3D>;
  joints: Map<string, Object3D>;
  materials: Map<string, MeshStandardMaterial>;
  stats: { meshesIn: number; batches: number; triangles: number; staticTriangles: number };
  dispose(): void;
}

/** Materials that need runtime tweaks the glTF export cannot express. */
function tuneMaterial(m: MeshStandardMaterial) {
  const n = m.name;
  if (n === "MAT_Glass") {
    m.transparent = true;
    // thin, clear, softly blue: several panes in a row must still read as clear glass
    m.opacity = 0.11;
    m.depthWrite = false;
    m.roughness = 0.05;
    m.metalness = 0;
    m.envMapIntensity = 0.75;
    m.side = DoubleSide;
    m.color.set("#cfe6f7");
  } else if (n === "MAT_Glass_Frosted") {
    m.transparent = true;
    m.opacity = 0.55;
    m.depthWrite = false;
    m.side = DoubleSide;
  } else if (n.startsWith("MAT_LED")) {
    m.toneMapped = true;
  } else if (n.startsWith("MAT_Leaf")) {
    m.side = DoubleSide;
  }
  // flat-shaded architectural colours read a little more crisply with a touch of env light
  if (m.envMapIntensity === 1) m.envMapIntensity = 0.85;
}

const SHADOWLESS = new Set(["MAT_Floor_Stone", "MAT_Floor_Wood", "MAT_Rug_Navy", "MAT_Rug_Cream", "MAT_Mat_Navy", "MAT_Glass", "MAT_Glass_Frosted"]);
const TEXTURED = /Floor|Wood_Light|Fabric|Rug|Mat_Navy/;

export function buildOfficeScene(gltfs: GLTF[], layout: OfficeLayout, maxAnisotropy: number): OfficeScene {
  const root = new Group();
  root.name = "Office";
  const screens = new Map<string, Mesh>();
  const signs = new Map<string, Mesh>();
  const dynamic = new Map<string, Object3D>();
  const joints = new Map<string, Object3D>();
  const materials = new Map<string, MeshStandardMaterial>();
  const dynamicIds = new Set(layout.items.filter((i) => i.collection === "dynamic" || i.type === "robot_arm").map((i) => i.id));
  const groups = new Map<string, { material: MeshStandardMaterial; geoms: BufferGeometry[] }>();
  let meshesIn = 0, triangles = 0, staticTriangles = 0;

  const shared = (m: Material): MeshStandardMaterial => {
    const sm = m as MeshStandardMaterial;
    let mat = materials.get(sm.name);
    if (!mat) {
      mat = sm;
      tuneMaterial(mat);
      for (const t of [mat.map, mat.normalMap, mat.roughnessMap, mat.emissiveMap]) {
        if (t && t.anisotropy < Math.min(8, maxAnisotropy)) { t.anisotropy = Math.min(8, maxAnisotropy); t.needsUpdate = true; }
      }
      materials.set(sm.name, mat);
    }
    return mat;
  };

  for (const gltf of gltfs) {
    // the GLB cache is shared between viewers: work on a clone (geometry and materials stay shared)
    const scene = gltf.scene.clone(true);
    scene.updateMatrixWorld(true);
    // 1. lift out the parts that stay live
    const keep: Object3D[] = [];
    scene.traverse((o) => {
      if (/^SCREEN_|^SIGN_/.test(o.name) && (o as Mesh).isMesh) keep.push(o);
      else if (dynamicIds.has(o.name)) keep.push(o);
    });
    for (const o of keep) {
      if (keep.some((k) => k !== o && isAncestor(k, o))) continue;
      const world = o.matrixWorld.clone();
      o.removeFromParent();
      o.matrix.copy(world);
      o.matrix.decompose(o.position, o.quaternion, o.scale);
      root.add(o);
      o.traverse((c) => {
        const mesh = c as Mesh;
        if (mesh.isMesh) {
          meshesIn++;
          mesh.material = Array.isArray(mesh.material) ? mesh.material.map(shared) : shared(mesh.material);
          mesh.castShadow = !/^SCREEN_|^SIGN_/.test(c.name);
          mesh.receiveShadow = true;
          triangles += triCount(mesh.geometry);
        }
        if (/_J\d$/.test(c.name)) joints.set(c.name, c);
      });
      if (o.name.startsWith("SCREEN_")) screens.set(o.name, o as Mesh);
      else if (o.name.startsWith("SIGN_")) signs.set(o.name, o as Mesh);
      else dynamic.set(o.name, o);
    }
    // 2. merge everything else by material
    scene.updateMatrixWorld(true);
    scene.traverse((o) => {
      const mesh = o as Mesh;
      if (!mesh.isMesh) return;
      meshesIn++;
      const mat = shared(mesh.material as Material);
      const g = mesh.geometry.clone().applyMatrix4(mesh.matrixWorld);
      const needUv = TEXTURED.test(mat.name) || !!mat.map || !!mat.normalMap;
      for (const name of Object.keys(g.attributes)) {
        if (name === "position" || name === "normal" || (name === "uv" && needUv)) continue;
        g.deleteAttribute(name);
      }
      if (needUv && !g.getAttribute("uv")) return;
      const entry = groups.get(mat.name) ?? groups.set(mat.name, { material: mat, geoms: [] }).get(mat.name)!;
      entry.geoms.push(g.index ? g : g.toNonIndexed());
      const tc = triCount(g);
      triangles += tc;
      staticTriangles += tc;
    });
  }
  let batches = 0;
  for (const { material, geoms } of groups.values()) {
    const indexed = geoms.filter((g) => g.index);
    const plain = geoms.filter((g) => !g.index);
    for (const set of [indexed, plain]) {
      if (!set.length) continue;
      const merged = mergeGeometries(set, false);
      for (const g of set) g.dispose();
      if (!merged) continue;
      merged.computeBoundingSphere();
      merged.computeBoundingBox();
      const mesh = new Mesh(merged, material);
      mesh.name = `Batch_${material.name}`;
      mesh.castShadow = !SHADOWLESS.has(material.name) && !material.name.startsWith("MAT_LED");
      mesh.receiveShadow = true;
      mesh.matrixAutoUpdate = false;
      if (material.transparent) mesh.renderOrder = 2;
      root.add(mesh);
      batches++;
    }
  }
  return {
    root, screens, signs, dynamic, joints, materials,
    stats: { meshesIn, batches, triangles, staticTriangles },
    dispose() {
      // merged batches are this viewer's own; materials and textures belong to the GLB cache
      root.traverse((o) => {
        const mesh = o as Mesh;
        if (mesh.isMesh && mesh.name.startsWith("Batch_")) mesh.geometry.dispose();
      });
      root.removeFromParent();
    },
  };
}

function isAncestor(a: Object3D, b: Object3D): boolean {
  for (let p = b.parent; p; p = p.parent) if (p === a) return true;
  return false;
}

function triCount(g: BufferGeometry): number {
  return (g.index ? g.index.count : g.getAttribute("position").count) / 3;
}
