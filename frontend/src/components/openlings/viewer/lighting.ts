import {
  BackSide, BufferAttribute, Color, DataTexture, DirectionalLight, DoubleSide, FloatType, Group, LinearFilter,
  LinearSRGBColorSpace, Mesh, MeshBasicMaterial, PlaneGeometry, PMREMGenerator, RGBAFormat, Scene, ShadowMaterial,
  SphereGeometry, Vector3, type Texture, type WebGLRenderer,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { LOOKDEV_CAMERA } from "../../../lib/openlings/cameraViews";
import { inverseNeutralToneMap, srgbToLinear, type RGB } from "../../../lib/openlings/neutralToneMap";

export type LightingPresetId = "studio" | "neutral";

export interface LightingPreset {
  id: LightingPresetId;
  label: string;
  /** Bloom state applied when switching to this preset. */
  bloom: boolean;
  /** Backdrop gradient, top to bottom: [fraction of the viewport height, sRGB hex as it should appear]. */
  backdrop: [number, string][];
  environment: "studio" | "room";
  environmentIntensity: number;
  key: { intensity: number; color: number; shadowRadius: number };
  contact: { intensity: number; shadowRadius: number };
  floorShadowOpacity: number;
}

/**
 * Studio reproduces the Blender LOOKDEV_Studio rig; Neutral is a generic, even room light used to
 * check that the materials hold up outside the staged studio (the 20_neutral_lighting_check render).
 */
export const LIGHTING_PRESETS: Record<LightingPresetId, LightingPreset> = {
  studio: {
    id: "studio",
    label: "Studio",
    bloom: true,
    // Sampled from 01_front.png: flat cyc wall, a soft horizon a little below mid-frame, bright floor.
    backdrop: [[0, "#d4d4d6"], [0.43, "#d5d5d7"], [0.48, "#dcdcde"], [0.53, "#efeff0"], [0.6, "#f9f9f9"], [1, "#f9f8f7"]],
    environment: "studio",
    environmentIntensity: 1,
    key: { intensity: 4.6, color: 0xfff7e8, shadowRadius: 14 },
    contact: { intensity: 0.6, shadowRadius: 6 },
    floorShadowOpacity: 0.2,
  },
  neutral: {
    id: "neutral",
    label: "Neutral",
    bloom: false,
    backdrop: [[0, "#8c8c8c"], [1, "#8c8c8c"]],
    environment: "room",
    environmentIntensity: 0.9,
    key: { intensity: 0.6, color: 0xffffff, shadowRadius: 14 },
    contact: { intensity: 0, shadowRadius: 6 },
    floorShadowOpacity: 0.08,
  },
};

/**
 * Blender LOOKDEV_* area lights at rig rotation 0, converted to Y-up (x, z, -y). Watts and sizes
 * are the Blender values; every panel is aimed at the character like the Blender lights are.
 * The key keeps only part of its energy in the environment because a shadow-casting directional
 * light carries the rest (and the shadows).
 */
const STUDIO_LIGHTS: { position: [number, number, number]; size: [number, number]; watts: number; color: [number, number, number]; envShare?: number }[] = [
  { position: [-1.7, 2.1, 2.1], size: [1.6, 1.6], watts: 240, color: [1.0, 0.97, 0.91], envShare: 0.45 }, // key
  { position: [2.3, 1.0, 1.6], size: [2.6, 2.6], watts: 50, color: [0.93, 0.96, 1.0] }, // fill
  { position: [1.4, 1.9, -1.9], size: [1.0, 1.8], watts: 200, color: [0.96, 0.98, 1.0] }, // rim
  { position: [-1.5, 1.6, -1.8], size: [1.0, 1.8], watts: 120, color: [1.0, 0.98, 0.95] }, // rim 2
  { position: [0, 3.0, 0.3], size: [2.2, 2.2], watts: 55, color: [1, 1, 1] }, // top
  { position: [0.2, 0.15, 2.2], size: [3.0, 3.0], watts: 48, color: [1.0, 0.98, 0.96] }, // bounce
];
/** Panel radiance per (watt / m²); calibrated against the reference renders. */
const PANEL_RADIANCE = 0.14;
const KEY_DIRECTION = new Vector3(-1.7, 2.1, 2.1).normalize();
const TOP_DIRECTION = new Vector3(0, 3.0, 0.3).normalize();

const aim = () => new Vector3(LOOKDEV_CAMERA.target.x, LOOKDEV_CAMERA.target.y, LOOKDEV_CAMERA.target.z);

/**
 * The Blender cyclorama as seen from the character: self-lit grey sweep and back wall behind,
 * bright lit floor below, and the dim open world toward the camera and overhead.
 */
function createSurroundings(): Mesh {
  const geometry = new SphereGeometry(20, 64, 32);
  const pos = geometry.getAttribute("position");
  const colors = new Float32Array(pos.count * 3);
  const d = new Vector3();
  const smooth = (a: number, b: number, x: number) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
  for (let i = 0; i < pos.count; i++) {
    d.fromBufferAttribute(pos, i).normalize();
    const behind = smooth(0.25, -0.35, d.z);
    const above = smooth(0.55, 0.9, d.y);
    let l = 0.18 + (0.68 - 0.18) * behind;
    l = l + (0.2 - l) * above;
    l = l + (0.95 - l) * smooth(0.02, -0.12, d.y);
    colors.set([l, l, l * 1.02], i * 3);
  }
  geometry.setAttribute("color", new BufferAttribute(colors, 3));
  return new Mesh(geometry, new MeshBasicMaterial({ vertexColors: true, side: BackSide }));
}

function createStudioEnvironmentScene(): Scene {
  const scene = new Scene();
  scene.add(createSurroundings());
  const target = aim();
  for (const light of STUDIO_LIGHTS) {
    const radiance = (PANEL_RADIANCE * light.watts * (light.envShare ?? 1)) / (light.size[0] * light.size[1]);
    const panel = new Mesh(
      new PlaneGeometry(light.size[0], light.size[1]),
      new MeshBasicMaterial({ color: new Color(...light.color).multiplyScalar(radiance), side: DoubleSide }),
    );
    panel.position.set(...light.position);
    panel.lookAt(target);
    scene.add(panel);
  }
  return scene;
}

function disposeScene(scene: Scene) {
  scene.traverse((o) => {
    if (o instanceof Mesh) { o.geometry.dispose(); (o.material as MeshBasicMaterial).dispose(); }
  });
}

/** Prefiltered environment maps for both presets, built once per renderer. */
export function createEnvironments(renderer: WebGLRenderer): Record<LightingPreset["environment"], Texture> & { dispose(): void } {
  const pmrem = new PMREMGenerator(renderer);
  const studioScene = createStudioEnvironmentScene();
  const studio = pmrem.fromScene(studioScene, 0, 0.1, 100, { size: 256, position: aim() }).texture;
  disposeScene(studioScene);
  const roomScene = new RoomEnvironment();
  const room = pmrem.fromScene(roomScene, 0.04).texture;
  roomScene.dispose();
  pmrem.dispose();
  return { studio, room, dispose: () => { studio.dispose(); room.dispose(); } };
}

/**
 * A vertical screen-space gradient for scene.background. Values are pre-compensated for the
 * Neutral tone map so the backdrop shows the listed colours at exposure 1, as in the references.
 */
export function createBackdropTexture(stops: LightingPreset["backdrop"]): DataTexture {
  const rows = 256;
  const data = new Float32Array(rows * 4);
  const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  for (let r = 0; r < rows; r++) {
    const f = 1 - r / (rows - 1); // DataTexture row 0 is the bottom of the screen.
    let i = 0;
    while (i < stops.length - 2 && f > stops[i + 1][0]) i++;
    const [f0, c0] = stops[i];
    const [f1, c1] = stops[Math.min(i + 1, stops.length - 1)];
    const t = f1 === f0 ? 0 : Math.min(1, Math.max(0, (f - f0) / (f1 - f0)));
    const a = rgb(c0), b = rgb(c1);
    const linear = a.map((v, c) => srgbToLinear(v + (b[c] - v) * t)) as RGB;
    data.set([...inverseNeutralToneMap(linear), 1], r * 4);
  }
  const texture = new DataTexture(data, 1, rows, RGBAFormat, FloatType);
  texture.colorSpace = LinearSRGBColorSpace;
  texture.magFilter = texture.minFilter = LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

/**
 * Directional lights that carry the shadows: the Blender key (soft, character + floor) and a
 * contact light from the overhead panel that grounds the shoes. They live in `rig`, which turns
 * with the camera like the Blender studio rig.
 */
export function createShadowLights() {
  const rig = new Group();
  // Soft (VSM-blurred) shadows stand in for the large Blender area lights.
  const make = (dir: Vector3, mapSize: number) => {
    const light = new DirectionalLight(0xffffff, 1);
    light.position.copy(dir).multiplyScalar(4).add(aim());
    light.target.position.copy(aim());
    light.castShadow = true;
    light.shadow.mapSize.set(mapSize, mapSize);
    const cam = light.shadow.camera;
    cam.left = cam.bottom = -1.1;
    cam.right = cam.top = 1.1;
    cam.near = 0.5;
    cam.far = 8;
    light.shadow.bias = -0.0005;
    light.shadow.normalBias = 0.01;
    light.shadow.blurSamples = 16;
    rig.add(light, light.target);
    return light;
  };
  const key = make(KEY_DIRECTION, 1024);
  const contact = make(TOP_DIRECTION, 1024);
  return { rig, key, contact };
}

/**
 * Resizes both shadow cameras to cover `half` metres around the aim point. Wider stages
 * (six Openlings, the props gallery) get a 2048 map so the shadows keep their softness.
 */
export function setShadowExtent(lights: ReturnType<typeof createShadowLights>, half: number) {
  for (const light of [lights.key, lights.contact]) {
    const cam = light.shadow.camera;
    if (cam.right === half) continue;
    cam.left = cam.bottom = -half;
    cam.right = cam.top = half;
    cam.updateProjectionMatrix();
    const size = half > 1.2 ? 2048 : 1024;
    if (light.shadow.mapSize.x !== size) {
      light.shadow.mapSize.set(size, size);
      light.shadow.map?.dispose();
      light.shadow.map = null;
    }
  }
}

export function applyLightingPreset(preset: LightingPreset, lights: ReturnType<typeof createShadowLights>, floor: Mesh<PlaneGeometry, ShadowMaterial>) {
  lights.key.intensity = preset.key.intensity;
  lights.key.color.set(preset.key.color);
  lights.key.shadow.radius = preset.key.shadowRadius;
  lights.contact.intensity = preset.contact.intensity;
  lights.contact.shadow.radius = preset.contact.shadowRadius;
  lights.contact.castShadow = preset.contact.intensity > 0;
  floor.material.opacity = preset.floorShadowOpacity;
}

/** An invisible floor at y = 0 that only shows the shadows. */
export function createFloor(): Mesh<PlaneGeometry, ShadowMaterial> {
  const floor = new Mesh(new PlaneGeometry(8, 8), new ShadowMaterial({ color: 0x1b1d24, opacity: 0.24 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  return floor;
}
