import {
  Color, DirectionalLight, Group, HemisphereLight, PMREMGenerator, PointLight, SpotLight, type DataTexture, type Texture, type WebGLRenderer,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import type { OfficeLight } from "../../../lib/office/layout";
import { createBackdropTexture } from "../../openlings/viewer/lighting";

export type OfficeLightingId = "day" | "evening";

export interface OfficeLightingPreset {
  id: OfficeLightingId;
  label: string;
  backdrop: [number, string][];
  exposure: number;
  environmentIntensity: number;
  sun: { intensity: number; color: string };
  sky: { intensity: number; sky: string; ground: string };
  accent: number;
  bloom: { strength: number; radius: number; threshold: number };
  /** Multiplier on LED emission (screens are unaffected). */
  led: number;
}

export const OFFICE_LIGHTING: Record<OfficeLightingId, OfficeLightingPreset> = {
  day: {
    id: "day", label: "Day",
    backdrop: [[0, "#e4e9f1"], [0.55, "#eef1f6"], [1, "#f4f2ee"]],
    exposure: 0.95, environmentIntensity: 0.42,
    sun: { intensity: 3.1, color: "#ffeed6" },
    sky: { intensity: 0.55, sky: "#e8efff", ground: "#d9d4ca" },
    accent: 1,
    bloom: { strength: 0.35, radius: 0.22, threshold: 2.9 },
    led: 1,
  },
  evening: {
    id: "evening", label: "Evening",
    backdrop: [[0, "#1b2440"], [0.6, "#253150"], [1, "#2f3a55"]],
    exposure: 1.0, environmentIntensity: 0.32,
    sun: { intensity: 0.55, color: "#ffc98f" },
    sky: { intensity: 0.42, sky: "#5d6f9c", ground: "#4a3b2d" },
    accent: 2.6,
    bloom: { strength: 0.45, radius: 0.3, threshold: 2.2 },
    led: 1.6,
  },
};

/**
 * World-anchored office lighting (it does not turn with the camera, unlike the character
 * lab's studio rig): a warm shadow-casting sun, sky fill, an environment for reflections and
 * a few accent lights from the layout (Command Hub key and cyan glow, warm Break and Research
 * lamps, cyan Ops and test-bay accents).
 */
export class OfficeLighting {
  readonly group = new Group();
  readonly sun: DirectionalLight;
  readonly sky: HemisphereLight;
  readonly accents: (PointLight | SpotLight)[] = [];
  private readonly accentBase = new Map<PointLight | SpotLight, number>();
  readonly environment: Texture;
  backdrop: DataTexture | null = null;

  constructor(renderer: WebGLRenderer, lights: OfficeLight[], bounds: [number, number, number, number]) {
    const pmrem = new PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    this.environment = pmrem.fromScene(room, 0.035).texture;
    room.dispose();
    pmrem.dispose();
    const sunSpec = lights.find((l) => l.type === "directional")!;
    this.sun = new DirectionalLight(sunSpec.color, sunSpec.intensity);
    this.sun.position.set(...sunSpec.position!);
    this.sun.target.position.set(...sunSpec.target!);
    this.sun.castShadow = true;
    const cam = this.sun.shadow.camera;
    const [x0, z0, x1, z1] = bounds;
    const half = Math.max(x1 - x0, z1 - z0) * 0.62;
    cam.left = cam.bottom = -half;
    cam.right = cam.top = half;
    cam.near = 2;
    cam.far = 40;
    this.sun.shadow.bias = -0.00035;
    this.sun.shadow.normalBias = 0.018;
    this.sun.shadow.radius = 2.2;
    this.sun.shadow.blurSamples = 12;
    this.group.add(this.sun, this.sun.target);
    const skySpec = lights.find((l) => l.type === "hemisphere")!;
    this.sky = new HemisphereLight(skySpec.sky, skySpec.ground, skySpec.intensity);
    this.group.add(this.sky);
    for (const l of lights) {
      if (l.type === "point") {
        const p = new PointLight(l.color, l.intensity, l.distance ?? 5, 2);
        p.position.set(...l.position!);
        this.accents.push(p);
        this.accentBase.set(p, l.intensity);
        this.group.add(p);
      } else if (l.type === "spot") {
        const s = new SpotLight(l.color, l.intensity, l.distance ?? 8, l.angle ?? 0.6, l.penumbra ?? 0.6, 2);
        s.position.set(...l.position!);
        s.target.position.set(...l.target!);
        this.accents.push(s);
        this.accentBase.set(s, l.intensity);
        this.group.add(s, s.target);
      }
    }
  }

  setShadowMapSize(size: number) {
    if (this.sun.shadow.mapSize.x === size) return;
    this.sun.shadow.mapSize.set(size, size);
    this.sun.shadow.map?.dispose();
    this.sun.shadow.map = null;
  }

  apply(p: OfficeLightingPreset) {
    this.sun.intensity = p.sun.intensity;
    this.sun.color.set(p.sun.color);
    this.sky.intensity = p.sky.intensity;
    this.sky.color.set(p.sky.sky);
    this.sky.groundColor.set(p.sky.ground);
    for (const a of this.accents) a.intensity = (this.accentBase.get(a) ?? 1) * p.accent;
    this.backdrop?.dispose();
    this.backdrop = createBackdropTexture(p.backdrop);
  }

  dispose() {
    this.environment.dispose();
    this.backdrop?.dispose();
    this.sun.shadow.map?.dispose();
    this.group.removeFromParent();
  }
}

/** Scales emission of LED materials for a lighting preset (remembering the authored value). */
export function scaleLeds(materials: Iterable<{ name: string; emissiveIntensity: number; userData: Record<string, unknown> }>, k: number) {
  for (const m of materials) {
    if (!m.name.startsWith("MAT_LED")) continue;
    const base = (m.userData.baseEmissive as number | undefined) ?? m.emissiveIntensity;
    m.userData.baseEmissive = base;
    m.emissiveIntensity = base * k;
  }
}

export const TMP_COLOR = new Color();
