import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CanvasTexture, Color, Group, LineBasicMaterial, LineLoop, LineSegments, Mesh,
  MeshBasicMaterial, Points, PointsMaterial, SphereGeometry, Sprite, SpriteMaterial, SRGBColorSpace, type Texture,
} from "three";
import { landPoints } from "../../../lib/office/worldMap";

/**
 * The Command Hub's luminous hologram globe: dotted continents, a faint lat/long grid, two
 * orbit rings with satellites and a soft halo. Cheap (a few draw calls, no postprocessing of
 * its own) and slow-moving; it floats behind and above the Commander.
 */
export class Globe {
  readonly group = new Group();
  private readonly spin = new Group();
  private readonly rings: Group[] = [];
  private readonly disposables: { dispose(): void }[] = [];
  private t = 0;

  constructor(radius: number) {
    this.group.name = "CommandGlobe";
    this.group.add(this.spin);
    // HDR colours (above the bloom threshold) so the hologram glows
    const cyan = new Color(0.55, 2.6, 3.4);
    // core: a deep blue translucent sphere
    const coreGeo = new SphereGeometry(radius * 0.97, 48, 24);
    const coreMat = new MeshBasicMaterial({ color: new Color(0.06, 0.32, 0.9), transparent: true, opacity: 0.5, depthWrite: false });
    const core = new Mesh(coreGeo, coreMat);
    core.renderOrder = 3;
    this.spin.add(core);
    // continents
    const pts = landPoints(5200);
    const landGeo = new BufferGeometry();
    for (let i = 0; i < pts.length; i++) pts[i] *= radius;
    landGeo.setAttribute("position", new BufferAttribute(pts, 3));
    const landMat = new PointsMaterial({ color: cyan, size: radius * 0.045, sizeAttenuation: true, transparent: true, opacity: 0.95,
      depthWrite: false, blending: AdditiveBlending });
    const land = new Points(landGeo, landMat);
    land.renderOrder = 4;
    this.spin.add(land);
    // graticule
    const grid: number[] = [];
    const seg = 48;
    for (let m = 0; m < 12; m++) {
      const lon = (m / 12) * Math.PI * 2;
      for (let i = 0; i < seg; i++) {
        for (const k of [i, i + 1]) {
          const lat = -Math.PI / 2 + (k / seg) * Math.PI;
          grid.push(Math.cos(lat) * Math.sin(lon) * radius, Math.sin(lat) * radius, Math.cos(lat) * Math.cos(lon) * radius);
        }
      }
    }
    for (let p = 1; p < 6; p++) {
      const lat = -Math.PI / 2 + (p / 6) * Math.PI;
      for (let i = 0; i < seg; i++) {
        for (const k of [i, i + 1]) {
          const lon = (k / seg) * Math.PI * 2;
          grid.push(Math.cos(lat) * Math.sin(lon) * radius, Math.sin(lat) * radius, Math.cos(lat) * Math.cos(lon) * radius);
        }
      }
    }
    const gridGeo = new BufferGeometry();
    gridGeo.setAttribute("position", new BufferAttribute(new Float32Array(grid), 3));
    const gridMat = new LineBasicMaterial({ color: new Color(0.3, 1.1, 2.0), transparent: true, opacity: 0.35, depthWrite: false, blending: AdditiveBlending });
    const gridLines = new LineSegments(gridGeo, gridMat);
    gridLines.renderOrder = 4;
    this.spin.add(gridLines);
    // orbit rings with satellites
    const ringMat = new LineBasicMaterial({ color: cyan, transparent: true, opacity: 0.55, depthWrite: false, blending: AdditiveBlending });
    const satMat = new MeshBasicMaterial({ color: new Color(2.5, 4, 4.5) });
    const satGeo = new SphereGeometry(radius * 0.035, 10, 6);
    for (const [tiltX, tiltZ, scale] of [[1.15, 0.35, 1.32], [1.9, -0.55, 1.22]] as const) {
      const ring = new Group();
      const n = 128;
      const pos = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2;
        pos.set([Math.cos(a) * radius * scale, 0, Math.sin(a) * radius * scale], i * 3);
      }
      const g = new BufferGeometry();
      g.setAttribute("position", new BufferAttribute(pos, 3));
      const loop = new LineLoop(g, ringMat);
      loop.renderOrder = 4;
      ring.add(loop);
      const sat = new Mesh(satGeo, satMat);
      sat.position.set(radius * scale, 0, 0);
      ring.add(sat);
      ring.rotation.set(tiltX, 0, tiltZ);
      this.group.add(ring);
      this.rings.push(ring);
      this.disposables.push(g);
    }
    // halo
    const halo = new Sprite(new SpriteMaterial({ map: haloTexture(), color: "#4fc8ff", transparent: true, opacity: 0.55, depthWrite: false,
      blending: AdditiveBlending }));
    halo.scale.setScalar(radius * 3.4);
    halo.renderOrder = 2;
    this.group.add(halo);
    this.disposables.push(coreGeo, coreMat, landGeo, landMat, gridGeo, gridMat, ringMat, satMat, satGeo, halo.material, halo.material.map as Texture);
  }

  update(dt: number) {
    this.t += dt;
    this.spin.rotation.y += dt * 0.16;
    this.rings[0].rotation.y += dt * 0.35;
    this.rings[1].rotation.y -= dt * 0.25;
    this.group.position.y = this.baseY + Math.sin(this.t * 0.8) * 0.015;
  }

  private baseY = 0;
  place(x: number, y: number, z: number) {
    this.baseY = y;
    this.group.position.set(x, y, z);
  }

  dispose() {
    for (const d of this.disposables) d.dispose();
    this.group.removeFromParent();
  }
}

function haloTexture(): CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 18, 64, 64, 64);
  grad.addColorStop(0, "rgba(120,220,255,0.0)");
  grad.addColorStop(0.42, "rgba(120,220,255,0.28)");
  grad.addColorStop(0.55, "rgba(90,190,255,0.12)");
  grad.addColorStop(1, "rgba(60,150,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}
