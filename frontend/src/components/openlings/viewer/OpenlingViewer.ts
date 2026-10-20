import {
  HalfFloatType, MathUtils, NeutralToneMapping, PerspectiveCamera, Scene, SRGBColorSpace, Spherical,
  Vector2, Vector3, VSMShadowMap, WebGLRenderTarget, WebGLRenderer, type DataTexture, type Object3D,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import {
  DEFAULT_VIEW, LOOKDEV_CAMERA, lensToFovDeg, verticalFovDeg, viewAzimuthDeg, viewPosition, type CameraViewId,
} from "../../../lib/openlings/cameraViews";
import {
  LIGHTING_PRESETS, applyLightingPreset, createBackdropTexture, createEnvironments, createFloor, createShadowLights,
  setShadowExtent, type LightingPresetId,
} from "./lighting";
import { OPENLING_PROPS_URL, gltfByteLength, instantiateOpenling, loadGltf, releaseGpuResources, type OpenlingStats } from "./loadOpenling";
import { LabStage, type StageMode } from "../runtime/LabStage";
import { PropLibrary } from "../runtime/PropLibrary";

/**
 * Bloom matched by eye to the Blender compositor glare (Bloom, threshold 2.5, strength 0.35). Only
 * the HDR status light (emission strength 9, luminance ≈ 4.8) clears the threshold; the metallic
 * badge's panel reflections (≈ 3–4), skin, zipper and backdrop stay below it.
 */
const BLOOM = { strength: 0.24, radius: 0, threshold: 4 };
/** Weights of the five bloom blur levels, finest first; the stock 1…0.2 ramp washes cyan over the jacket. */
const BLOOM_LEVELS = [1, 0.45, 0.12, 0.02, 0];
/**
 * Ambient occlusion in metres: the raytraced Blender render darkens the skin under the jacket hem
 * and collar and grounds the shoes; screen-space GTAO approximates that (the floor plane is part
 * of its depth/normal pass, so it also gives the contact shading where shoes meet the floor).
 */
const AO = { radius: 0.07, distanceExponent: 1.2, thickness: 0.5, scale: 1, samples: 16, blend: 0.7 };
const MAX_PIXEL_RATIO = 2;
const TRANSITION_MS = 650;
const FOV_DEG = lensToFovDeg(LOOKDEV_CAMERA.lensMm, LOOKDEV_CAMERA.sensorMm);

export interface ViewerOptions {
  modelUrl: string;
  /** Rigged asset: load the props too and drive it through a LabStage (animation, expressions, props). */
  animated?: boolean;
  propsUrl?: string;
  onProgress?: (fraction: number) => void;
  onLoad?: (stats: OpenlingStats & { loadMs: number; drawCalls: number; bytes: number | null }) => void;
  onError?: (error: Error) => void;
}

export function isWebGL2Available(): boolean {
  try {
    return !!document.createElement("canvas").getContext("webgl2");
  } catch {
    return false;
  }
}

export class OpenlingViewer {
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(FOV_DEG, 1, 0.05, 50);
  private readonly controls: OrbitControls;
  private readonly composer: EffectComposer;
  private readonly bloom: UnrealBloomPass;
  private readonly environments: ReturnType<typeof createEnvironments>;
  private readonly lights = createShadowLights();
  private readonly floor = createFloor();
  private readonly target = new Vector3(LOOKDEV_CAMERA.target.x, LOOKDEV_CAMERA.target.y, LOOKDEV_CAMERA.target.z);
  private readonly resizeObserver: ResizeObserver;
  private backdrop: DataTexture | null = null;
  private model: Object3D | null = null;
  /** Animated lab content (null for the static lookdev model). */
  stage: LabStage | null = null;
  private lastFrame = -1;
  private viewDistance: number = LOOKDEV_CAMERA.distance;
  private heightRatio = (LOOKDEV_CAMERA.height - LOOKDEV_CAMERA.target.y) / LOOKDEV_CAMERA.distance;
  private facingDeg = 0;
  private needsRender = true;
  private disposed = false;
  // Camera preset transition, interpolated in spherical coordinates around the target.
  private readonly from = new Spherical();
  private readonly to = new Spherical();
  private readonly offset = new Vector3();
  private transitionStart = -1;
  private benchmarkFrames: number[] | null = null;

  private readonly container: HTMLElement;
  private readonly options: ViewerOptions;

  constructor(container: HTMLElement, options: ViewerOptions) {
    this.container = container;
    this.options = options;
    this.renderer = new WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO));
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = NeutralToneMapping; // Blender view transform: Khronos PBR Neutral
    this.renderer.toneMappingExposure = 1;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = VSMShadowMap;
    // Count draw calls across every pass of a frame (shadow maps, scene, bloom, output), not just the last.
    this.renderer.info.autoReset = false;
    const canvas = this.renderer.domElement;
    canvas.style.display = "block";
    canvas.style.width = canvas.style.height = "100%";
    canvas.style.touchAction = "none";
    container.appendChild(canvas);

    // Half-float, multisampled scene buffer: the status light stays HDR for bloom, and the
    // OutputPass applies exposure, tone mapping and sRGB once at the end.
    const sceneTarget = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, sceneTarget);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    const ao = new GTAOPass(this.scene, this.camera, 1, 1);
    ao.updateGtaoMaterial({ radius: AO.radius, distanceExponent: AO.distanceExponent, thickness: AO.thickness, scale: AO.scale, samples: AO.samples });
    ao.blendIntensity = AO.blend;
    this.composer.addPass(ao);
    this.bloom = new UnrealBloomPass(new Vector2(1, 1), BLOOM.strength, BLOOM.radius, BLOOM.threshold);
    this.bloom.compositeMaterial.uniforms.bloomFactors.value = BLOOM_LEVELS;
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.environments = createEnvironments(this.renderer);
    this.scene.add(this.lights.rig, this.floor);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.copy(this.target);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enablePan = false;
    this.controls.minDistance = 1.3;
    this.controls.maxDistance = 6;
    this.controls.minPolarAngle = MathUtils.degToRad(25);
    this.controls.maxPolarAngle = MathUtils.degToRad(92);
    this.controls.addEventListener("change", this.invalidate);
    this.controls.addEventListener("start", this.cancelTransition);

    this.setLighting("studio");
    this.setView("reset", false);
    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.resize();
    this.renderer.setAnimationLoop(this.tick);
    void this.load();
  }

  private async load() {
    const started = performance.now();
    try {
      if (this.options.animated) {
        const [gltf, propsGltf] = await Promise.all([
          loadGltf(this.options.modelUrl, this.options.onProgress),
          loadGltf(this.options.propsUrl ?? OPENLING_PROPS_URL),
        ]);
        if (this.disposed) return;
        this.stage = new LabStage(gltf, new PropLibrary(propsGltf), this.renderer.capabilities.getMaxAnisotropy());
        this.stage.setMode("single");
        this.scene.add(this.stage.group);
        const stats = this.stage.primary!.stats;
        this.facingDeg = stats.facingDeg ?? 0;
        if (this.facingDeg !== 0) this.setView("reset", false);
        this.render();
        this.options.onLoad?.({ ...stats, loadMs: Math.round(performance.now() - started), drawCalls: this.renderer.info.render.calls, bytes: gltfByteLength(this.options.modelUrl) });
        return;
      }
      const gltf = await loadGltf(this.options.modelUrl, this.options.onProgress);
      if (this.disposed) return;
      const { root, stats } = instantiateOpenling(gltf, this.renderer.capabilities.getMaxAnisotropy());
      this.model = root;
      this.facingDeg = stats.facingDeg ?? 0;
      this.scene.add(root);
      // Presets were framed for a character facing +Z; re-frame if the asset faces elsewhere.
      if (this.facingDeg !== 0) this.setView("reset", false);
      this.render();
      this.options.onLoad?.({ ...stats, loadMs: Math.round(performance.now() - started), drawCalls: this.renderer.info.render.calls, bytes: gltfByteLength(this.options.modelUrl) });
    } catch (error) {
      if (!this.disposed) this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
    }
  }

  setView(id: CameraViewId | "reset", animate = true) {
    // Every preset restores the reference framing (distance and elevation) of its Blender render.
    const p = viewPosition(viewAzimuthDeg(id === "reset" ? DEFAULT_VIEW : id), this.facingDeg, this.viewDistance);
    // viewPosition is relative to the lookdev aim point; keep the same offset around the current
    // target, at the current stage's camera height (the lookdev elevation for one Openling).
    this.to.setFromVector3(this.offset.set(p.x - LOOKDEV_CAMERA.target.x, this.heightRatio * this.viewDistance, p.z - LOOKDEV_CAMERA.target.z));
    if (!animate) {
      this.transitionStart = -1;
      this.camera.position.setFromSpherical(this.to).add(this.target);
      this.stopInertia();
    } else {
      this.from.setFromVector3(this.offset.copy(this.camera.position).sub(this.target));
      // Take the short way around.
      const delta = MathUtils.euclideanModulo(this.to.theta - this.from.theta + Math.PI, Math.PI * 2) - Math.PI;
      this.to.theta = this.from.theta + delta;
      this.transitionStart = performance.now();
      this.stopInertia();
    }
    this.invalidate();
  }

  setLighting(id: LightingPresetId) {
    const preset = LIGHTING_PRESETS[id];
    this.scene.environment = this.environments[preset.environment];
    this.scene.environmentIntensity = preset.environmentIntensity;
    this.backdrop?.dispose();
    this.backdrop = createBackdropTexture(preset.backdrop);
    this.scene.background = this.backdrop;
    applyLightingPreset(preset, this.lights, this.floor);
    this.invalidate();
  }

  setBloom(enabled: boolean) {
    this.bloom.enabled = enabled;
    this.invalidate();
  }

  setExposure(exposure: number) {
    this.renderer.toneMappingExposure = exposure;
    this.invalidate();
  }

  /** Switches the animated lab between one Openling, the six roles together and the props gallery. */
  setStageMode(mode: StageMode) {
    if (!this.stage) return;
    this.stage.setMode(mode);
    const f = this.stage.framing();
    this.target.copy(f.target);
    this.controls.target.copy(f.target);
    this.viewDistance = f.distance;
    this.heightRatio = f.heightRatio;
    this.controls.minDistance = f.minDistance;
    this.controls.maxDistance = f.maxDistance;
    setShadowExtent(this.lights, f.shadowHalf);
    this.setView(f.view, false);
  }

  /**
   * Renders every animation frame for `ms` and reports the achieved frame timing. Used by the lab's
   * validation script; normal operation only renders when something changes.
   */
  benchmark(ms = 3000): Promise<{ frames: number; fps: number; avgFrameMs: number; p95FrameMs: number; drawCalls: number; triangles: number }> {
    this.benchmarkFrames = [];
    return new Promise((resolve) => {
      setTimeout(() => {
        const stamps = this.benchmarkFrames ?? [];
        this.benchmarkFrames = null;
        const deltas = stamps.slice(1).map((t, i) => t - stamps[i]).sort((a, b) => a - b);
        const avg = deltas.reduce((a, b) => a + b, 0) / Math.max(1, deltas.length);
        resolve({
          frames: deltas.length,
          fps: Math.round(1000 / avg),
          avgFrameMs: +avg.toFixed(2),
          p95FrameMs: +(deltas[Math.floor(deltas.length * 0.95)] ?? 0).toFixed(2),
          drawCalls: this.renderer.info.render.calls,
          triangles: this.renderer.info.render.triangles,
        });
      }, ms);
    });
  }

  private readonly invalidate = () => {
    this.needsRender = true;
  };

  private readonly cancelTransition = () => {
    this.transitionStart = -1;
  };

  /** OrbitControls keeps damping momentum between updates; one undamped update clears it. */
  private stopInertia() {
    this.controls.enableDamping = false;
    this.controls.update();
    this.controls.enableDamping = true;
  }

  private readonly resize = () => {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(this.renderer.getPixelRatio());
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.fov = verticalFovDeg(FOV_DEG, this.camera.aspect);
    this.camera.updateProjectionMatrix();
    this.invalidate();
  };

  private readonly tick = (now: number) => {
    const dt = this.lastFrame < 0 ? 0 : Math.min(0.1, (now - this.lastFrame) / 1000);
    this.lastFrame = now;
    if (this.stage?.isAnimating()) {
      this.stage.update(dt);
      this.needsRender = true;
    }
    if (this.transitionStart >= 0) {
      const t = Math.min(1, (now - this.transitionStart) / TRANSITION_MS);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2; // easeInOutCubic
      this.offset.setFromSphericalCoords(
        MathUtils.lerp(this.from.radius, this.to.radius, e),
        MathUtils.lerp(this.from.phi, this.to.phi, e),
        MathUtils.lerp(this.from.theta, this.to.theta, e),
      );
      this.camera.position.copy(this.offset).add(this.target);
      if (t >= 1) this.transitionStart = -1;
      this.needsRender = true;
    }
    this.controls.update(); // fires "change" while damping
    if (this.benchmarkFrames) this.benchmarkFrames.push(now);
    else if (!this.needsRender) return;
    this.needsRender = false;
    // Like the Blender rig, the studio (lights, shadows, environment) turns with the camera.
    const azimuth = Math.atan2(this.camera.position.x - this.target.x, this.camera.position.z - this.target.z);
    this.lights.rig.rotation.y = azimuth;
    this.scene.environmentRotation.y = azimuth;
    this.render();
  };

  private render() {
    this.renderer.info.reset();
    this.composer.render();
  }

  dispose() {
    this.disposed = true;
    this.renderer.setAnimationLoop(null);
    this.resizeObserver.disconnect();
    releaseGpuResources(this.scene);
    this.controls.removeEventListener("change", this.invalidate);
    this.controls.removeEventListener("start", this.cancelTransition);
    // OrbitControls removes its document keydown listener via getRootNode(), which is no longer the
    // document once React has detached the canvas; remove it from the owner document as well.
    const controls = this.controls as OrbitControls & { _interceptControlDown?: EventListener };
    if (controls._interceptControlDown) controls.domElement?.ownerDocument.removeEventListener("keydown", controls._interceptControlDown, { capture: true });
    this.controls.dispose();
    this.composer.passes.forEach((p) => p.dispose());
    this.composer.dispose();
    this.environments.dispose();
    this.backdrop?.dispose();
    this.floor.geometry.dispose();
    this.floor.material.dispose();
    this.lights.rig.traverse((o) => (o as { shadow?: { dispose(): void } }).shadow?.dispose());
    // The model's geometry, materials and textures belong to the shared GLB cache: detach only.
    if (this.model) this.scene.remove(this.model);
    this.stage?.dispose();
    this.stage = null;
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
