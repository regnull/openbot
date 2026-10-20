import { MathUtils, Vector3, type PerspectiveCamera } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { OfficeCamera } from "../../../lib/office/layout";

const TRANSITION_S = 1.1;

/**
 * Orbit / pan / zoom around the office with limits (never under the floor, never far
 * outside the building), smooth transitions between presets, and focus / follow for agents.
 */
export class CameraRig {
  readonly controls: OrbitControls;
  private readonly camera: PerspectiveCamera;
  private readonly bounds: [number, number, number, number];
  private from = { pos: new Vector3(), target: new Vector3(), fov: 30, shift: [0, 0] as [number, number] };
  private to = { pos: new Vector3(), target: new Vector3(), fov: 30, shift: [0, 0] as [number, number] };
  /** Where the target appears on screen (NDC): off-centre when a panel covers part of the view. */
  private shift: [number, number] = [0, 0];
  private t = -1;
  private follow: (() => Vector3) | null = null;
  private followOffset = new Vector3();
  private onChange: () => void;
  /** The user has orbited/zoomed since the last preset (the viewer then stops auto-refitting). */
  userMoved = false;

  constructor(camera: PerspectiveCamera, dom: HTMLElement, bounds: [number, number, number, number], onChange: () => void) {
    this.camera = camera;
    this.bounds = bounds;
    this.onChange = onChange;
    const c = new OrbitControls(camera, dom);
    c.enableDamping = true;
    c.dampingFactor = 0.09;
    c.screenSpacePanning = false; // pan across the floor plane
    c.minDistance = 1.1;
    c.maxDistance = 34;
    c.maxPolarAngle = MathUtils.degToRad(82);
    c.minPolarAngle = MathUtils.degToRad(4);
    c.zoomSpeed = 0.9;
    c.panSpeed = 0.9;
    c.addEventListener("change", () => {
      this.clampTarget();
      this.onChange();
    });
    c.addEventListener("start", () => {
      // the user takes over: stop transitions; keep following only for orbit/zoom
      this.t = -1;
      this.userMoved = true;
    });
    this.controls = c;
  }

  private clampTarget() {
    const [x0, z0, x1, z1] = this.bounds;
    const t = this.controls.target;
    const cx = MathUtils.clamp(t.x, x0 - 1, x1 + 1), cz = MathUtils.clamp(t.z, z0 - 1, z1 + 2), cy = MathUtils.clamp(t.y, 0, 2.5);
    if (cx !== t.x || cz !== t.z || cy !== t.y) {
      const dx = cx - t.x, dy = cy - t.y, dz = cz - t.z;
      t.set(cx, cy, cz);
      this.camera.position.x += dx;
      this.camera.position.y += dy;
      this.camera.position.z += dz;
    }
    if (this.camera.position.y < 0.25) this.camera.position.y = 0.25;
  }

  /**
   * Jumps or glides to a preset view. `shift` puts the target off-centre on screen (NDC, e.g. [-0.25, 0]:
   * a quarter of the view left of centre) by shifting the projection, so orbiting still pivots on it.
   */
  go(view: Pick<OfficeCamera, "position" | "target" | "fov"> & { shift?: [number, number] }, animate = true) {
    this.follow = null;
    this.userMoved = false;
    this.to.pos.set(...view.position);
    this.to.target.set(...view.target);
    this.to.fov = view.fov;
    this.to.shift = view.shift ?? [0, 0];
    if (!animate) {
      this.camera.position.copy(this.to.pos);
      this.controls.target.copy(this.to.target);
      this.setFov(view.fov);
      this.setShift(this.to.shift);
      this.t = -1;
      this.stopInertia();
      this.onChange();
      return;
    }
    this.from.pos.copy(this.camera.position);
    this.from.target.copy(this.controls.target);
    this.from.fov = this.camera.fov;
    this.from.shift = [...this.shift];
    this.t = 0;
  }

  private setShift([x, y]: [number, number]) {
    this.shift = [x, y];
    if (Math.abs(x) < 1e-4 && Math.abs(y) < 1e-4) {
      if (this.camera.view?.enabled) this.camera.clearViewOffset();
      return;
    }
    // a window of the same size, moved: the frustum slides, the target lands at (x, y) in NDC
    const fw = 1000 * this.camera.aspect, fh = 1000;
    this.camera.setViewOffset(fw, fh, (-x * fw) / 2, (y * fh) / 2, fw, fh);
  }

  /** Re-applies the screen shift after the viewport changed shape. */
  resize() {
    this.setShift(this.shift);
  }

  /** Frames a point (an agent) from the current direction at a close distance. */
  focus(point: Vector3, distance = 4.2) {
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    if (dir.y < 0.35) { dir.y = 0.35; dir.normalize(); }
    const target = point.clone().add(new Vector3(0, 0.45, 0));
    this.go({ position: target.clone().addScaledVector(dir, distance).toArray() as [number, number, number], target: target.toArray() as [number, number, number], fov: 34 });
  }

  /** Keeps the camera trained on a moving point until another view is chosen. */
  setFollow(get: (() => Vector3) | null) {
    this.follow = get;
    if (get) this.followOffset.copy(this.camera.position).sub(this.controls.target);
  }

  get following(): boolean {
    return !!this.follow;
  }

  private setFov(fov: number) {
    if (Math.abs(this.camera.fov - fov) > 1e-3) {
      this.camera.fov = fov;
      this.camera.updateProjectionMatrix();
    }
  }

  private stopInertia() {
    this.controls.enableDamping = false;
    this.controls.update();
    this.controls.enableDamping = true;
  }

  /** Returns true while the camera is moving by itself. */
  update(dt: number): boolean {
    let moving = false;
    if (this.t >= 0) {
      this.t = Math.min(1, this.t + dt / TRANSITION_S);
      const e = this.t < 0.5 ? 4 * this.t ** 3 : 1 - (-2 * this.t + 2) ** 3 / 2;
      this.camera.position.lerpVectors(this.from.pos, this.to.pos, e);
      this.controls.target.lerpVectors(this.from.target, this.to.target, e);
      this.setFov(MathUtils.lerp(this.from.fov, this.to.fov, e));
      this.setShift([MathUtils.lerp(this.from.shift[0], this.to.shift[0], e), MathUtils.lerp(this.from.shift[1], this.to.shift[1], e)]);
      if (this.t >= 1) {
        this.t = -1;
        this.stopInertia();
        if (this.follow) this.followOffset.copy(this.camera.position).sub(this.controls.target);
      }
      moving = true;
    } else if (this.follow) {
      const p = this.follow().clone().add(new Vector3(0, 0.45, 0));
      const k = 1 - Math.exp(-dt * 4);
      const delta = p.sub(this.controls.target).multiplyScalar(k);
      this.controls.target.add(delta);
      this.camera.position.add(delta);
      moving = delta.lengthSq() > 1e-8;
    }
    this.controls.update();
    return moving;
  }

  dispose() {
    // OrbitControls removes its capture-phase keydown listener from domElement.getRootNode(), which is no
    // longer the document once React has detached the canvas; left there, it keeps this rig and (through
    // onChange) the whole office viewer alive after unmount. Remove it from the owner document as well.
    const c = this.controls as OrbitControls & { _interceptControlDown?: EventListener };
    if (c._interceptControlDown) c.domElement?.ownerDocument.removeEventListener("keydown", c._interceptControlDown, { capture: true });
    this.controls.dispose();
  }
}
