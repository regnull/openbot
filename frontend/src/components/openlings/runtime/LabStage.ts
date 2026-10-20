import {
  Box3, BoxGeometry, CylinderGeometry, Group, Mesh, MeshStandardMaterial, Vector3, type Object3D,
} from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { DESK_HEIGHT, SEAT_HEIGHT, clipInfo } from "../../../lib/openlings/animations";
import { PROP_IDS } from "../../../lib/openlings/props";
import { ROLES, type RoleId } from "../../../lib/openlings/roles";
import { OpenlingCharacter } from "./OpenlingCharacter";
import type { PropLibrary } from "./PropLibrary";

export type StageMode = "single" | "multi" | "props";

export interface StageFraming {
  target: Vector3;
  distance: number;
  minDistance: number;
  maxDistance: number;
  /** Half-size of the shadow cameras, metres. */
  shadowHalf: number;
  /** Camera height above the target per metre of distance (the lookdev rig: 0.12 / 2.75). */
  heightRatio: number;
  /** Camera preset the stage opens on. */
  view: "front" | "threeQuarter";
}

interface Fixtures {
  group: Group;
  seat: Mesh;
  desk: Group;
}

/** Multi-agent layout: one shallow arc, every Openling (and the Coder's desk) in clear view. */
const MULTI_ROLES: RoleId[] = ["coder", "ops", "tester", "commander", "reporter", "researcher"];
const MULTI_LAYOUT = MULTI_ROLES.map((role, i) => {
  const x = (i - (MULTI_ROLES.length - 1) / 2) * 0.9;
  return { role, x, z: -0.4 * (1 - (x / 2.25) ** 2) };
});

/**
 * What the lab shows: one Openling, six role variants together, or the props gallery.
 * Seat and desk are lab fixtures (they appear while a character sits or uses the desk);
 * they are not part of either GLB.
 */
export class LabStage {
  readonly group = new Group();
  private modeValue: StageMode = "single";
  private placed: { character: OpenlingCharacter; fixtures: Fixtures; role?: RoleId }[] = [];
  private gallery: Group | null = null;
  private readonly fixtureMaterial = new MeshStandardMaterial({ color: 0xc8cdd6, roughness: 0.62, metalness: 0 });
  private readonly seatGeometry = new CylinderGeometry(0.19, 0.19, SEAT_HEIGHT, 48);
  private readonly deskTop = new BoxGeometry(0.84, 0.024, 0.36);
  private readonly deskLeg = new BoxGeometry(0.026, DESK_HEIGHT - 0.024, 0.026);
  private readonly characterGltf: GLTF;
  private readonly props: PropLibrary | null;
  private readonly maxAnisotropy: number;
  private spin = 0;

  constructor(characterGltf: GLTF, props: PropLibrary | null, maxAnisotropy: number) {
    this.characterGltf = characterGltf;
    this.props = props;
    this.maxAnisotropy = maxAnisotropy;
    this.group.name = "LabStage";
  }

  get mode(): StageMode {
    return this.modeValue;
  }

  /** The character the single-Openling controls drive. */
  get primary(): OpenlingCharacter | null {
    return this.modeValue === "single" ? this.placed[0]?.character ?? null : null;
  }

  get characters(): OpenlingCharacter[] {
    return this.placed.map((p) => p.character);
  }

  roleOf(character: OpenlingCharacter): RoleId | undefined {
    return this.placed.find((p) => p.character === character)?.role;
  }

  setMode(mode: StageMode) {
    this.clear();
    this.modeValue = mode;
    if (mode === "single") {
      this.add(0, 0, 0, 1).character.play("Idle");
    } else if (mode === "multi") {
      MULTI_LAYOUT.forEach((slot, i) => {
        const p = this.add(slot.x, slot.z, -slot.x * 0.12, 11 + i * 7);
        p.role = slot.role;
        p.character.applyRole(ROLES.find((r) => r.id === slot.role)!);
        // Different start times, so no two Openlings move (or blink) in lockstep.
        p.character.update(0.37 * i + 0.11);
      });
    } else {
      this.buildGallery();
    }
  }

  private add(x: number, z: number, yaw: number, seed: number) {
    const character = new OpenlingCharacter(this.characterGltf, this.props, { seed, maxAnisotropy: this.maxAnisotropy });
    character.root.position.set(x, 0, z);
    character.root.rotation.y = yaw;
    const fixtures = this.createFixtures();
    character.root.add(fixtures.group);
    this.group.add(character.root);
    const placed = { character, fixtures } as { character: OpenlingCharacter; fixtures: Fixtures; role?: RoleId };
    this.placed.push(placed);
    return placed;
  }

  private createFixtures(): Fixtures {
    const group = new Group();
    group.name = "LabFixtures";
    const seat = new Mesh(this.seatGeometry, this.fixtureMaterial);
    seat.position.set(0, SEAT_HEIGHT / 2, -0.06);
    const desk = new Group();
    const top = new Mesh(this.deskTop, this.fixtureMaterial);
    // Socket_DeskInteraction (laptop base centre) is at y 0.15, z 0.358; the desk's near edge is 2.5 cm from the belly.
    top.position.set(0, DESK_HEIGHT - 0.012, 0.43);
    desk.add(top);
    for (const [x, z] of [[-0.39, 0.27], [0.39, 0.27], [-0.39, 0.59], [0.39, 0.59]]) {
      const leg = new Mesh(this.deskLeg, this.fixtureMaterial);
      leg.position.set(x, (DESK_HEIGHT - 0.024) / 2, z);
      desk.add(leg);
    }
    for (const m of [seat, ...desk.children] as Mesh[]) m.castShadow = m.receiveShadow = true;
    group.add(seat, desk);
    seat.visible = desk.visible = false;
    return { group, seat, desk };
  }

  private buildGallery() {
    if (!this.props) return;
    const g = new Group();
    g.name = "PropsGallery";
    const cols = 5, dx = 0.44, dz = 0.5;
    PROP_IDS.forEach((id, i) => {
      const item = this.props!.instantiate(id);
      const holder = new Group();
      holder.name = `Gallery_${id}`;
      holder.userData.propId = id;
      // centre each prop over its turntable spot, resting on the floor
      const box = new Box3().setFromObject(item);
      const c = box.getCenter(new Vector3());
      item.position.set(-c.x, -box.min.y, -c.z);
      holder.add(item);
      const row = Math.floor(i / cols), col = i % cols;
      const n = row === 2 ? PROP_IDS.length - 2 * cols : cols;
      holder.position.set((col - (n - 1) / 2) * dx, 0, (row - 1) * dz);
      holder.rotation.y = 0.5;
      g.add(holder);
    });
    this.gallery = g;
    this.group.add(g);
  }

  /** Gallery item for a prop (null outside the gallery). */
  galleryItem(id: string): Object3D | null {
    return this.gallery?.getObjectByName(`Gallery_${id}`) ?? null;
  }

  setGallerySpin(on: boolean) {
    this.spin = on ? 0.35 : 0;
  }

  update(dt: number) {
    for (const p of this.placed) {
      p.character.update(dt);
      const s = p.character.state;
      const seated = !!s.clip && !s.restPose && clipInfo(s.clip).seated;
      p.fixtures.seat.visible = seated;
      p.fixtures.desk.visible = (seated && s.clip === "Typing") || Object.values(s.loadout).includes("desk");
    }
    if (this.gallery && this.spin) for (const h of this.gallery.children) h.rotation.y += this.spin * dt;
  }

  isAnimating(): boolean {
    return this.placed.length > 0 || (!!this.gallery && this.spin > 0);
  }

  framing(): StageFraming {
    if (this.modeValue === "multi") return { target: new Vector3(0, 0.45, -0.2), distance: 10.5, minDistance: 2, maxDistance: 16, shadowHalf: 2.9, heightRatio: 0.24, view: "front" };
    if (this.modeValue === "props") return { target: new Vector3(0, 0.1, 0), distance: 3.2, minDistance: 0.8, maxDistance: 8, shadowHalf: 1.6, heightRatio: 0.45, view: "front" };
    return { target: new Vector3(0, 0.5, 0), distance: 2.75, minDistance: 1.3, maxDistance: 6, shadowHalf: 1.1, heightRatio: 0.12 / 2.75, view: "threeQuarter" };
  }

  private clear() {
    for (const p of this.placed) p.character.dispose();
    this.placed = [];
    if (this.gallery) {
      this.gallery.removeFromParent();
      this.gallery = null;
    }
  }

  dispose() {
    this.clear();
    this.seatGeometry.dispose();
    this.deskTop.dispose();
    this.deskLeg.dispose();
    this.fixtureMaterial.dispose();
    this.group.removeFromParent();
  }
}
