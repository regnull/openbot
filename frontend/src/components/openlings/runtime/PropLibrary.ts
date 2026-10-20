import { Mesh, type Material, type Object3D } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { PROPS, PROP_IDS, type PropId } from "../../../lib/openlings/props";

/**
 * The props GLB, loaded once and shared. `instantiate` clones one prop's node tree; the
 * clones share geometry and materials with the template, so adding or removing props
 * never allocates GPU resources after the first draw.
 */
export class PropLibrary {
  private readonly templates = new Map<PropId, Object3D>();

  constructor(gltf: GLTF) {
    for (const id of PROP_IDS) {
      const node = gltf.scene.getObjectByName(PROPS[id].node);
      if (!node) throw new Error(`The props asset has no "${PROPS[id].node}" node.`);
      node.traverse((o) => {
        if (!(o instanceof Mesh)) return;
        o.castShadow = true;
        o.receiveShadow = true;
        for (const m of [o.material].flat() as Material[]) {
          // see-through lenses and visor: draw after the face, never hide it in the depth buffer
          if (m.transparent) m.depthWrite = false;
        }
      });
      this.templates.set(id, node);
    }
  }

  instantiate(id: PropId): Object3D {
    const obj = this.templates.get(id)!.clone(true);
    obj.position.set(0, 0, 0);
    obj.quaternion.identity();
    obj.name = `${PROPS[id].node}_Instance`;
    obj.userData.propId = id;
    return obj;
  }

  /** Triangles of one prop (for the lab's stats). */
  triangles(id: PropId): number {
    let t = 0;
    this.templates.get(id)!.traverse((o) => {
      if (!(o instanceof Mesh)) return;
      const g = o.geometry;
      t += (g.index ? g.index.count : g.getAttribute("position").count) / 3;
    });
    return t;
  }
}
