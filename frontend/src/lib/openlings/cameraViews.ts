/**
 * Camera framing for the Openling character lab, taken from the Blender lookdev rig the
 * character was approved on: a 70 mm lens on a 36 mm sensor, 2.75 m in front of the
 * character at 0.62 m height, aimed at (0, 0, 0.5). Every reference view rotates the whole studio
 * rig (camera + lights + backdrop) about the vertical axis; the character never moves.
 *
 * Blender is Z-up and glTF / three.js is Y-up: Blender (x, y, z) -> three (x, z, -y). The
 * character faces Blender -Y, which becomes three +Z. Azimuths here are degrees about +Y, measured
 * from the character's facing direction; positive swings the camera to the character's left (+X),
 * matching the rig rotation sign used for the Blender renders.
 */
export type CameraViewId = "front" | "threeQuarter" | "left" | "right" | "back";

export const CAMERA_VIEWS: readonly { id: CameraViewId; label: string; azimuthDeg: number }[] = [
  { id: "front", label: "Front", azimuthDeg: 0 },
  { id: "threeQuarter", label: "Front ¾", azimuthDeg: 40 },
  { id: "left", label: "Left", azimuthDeg: 90 },
  { id: "right", label: "Right", azimuthDeg: -90 },
  { id: "back", label: "Back", azimuthDeg: 180 },
];

/** The view the lab opens on and returns to on Reset. */
export const DEFAULT_VIEW: CameraViewId = "threeQuarter";

export const LOOKDEV_CAMERA = {
  distance: 2.75,
  height: 0.62,
  target: { x: 0, y: 0.5, z: 0 },
  lensMm: 70,
  sensorMm: 36,
} as const;

const toRad = (deg: number) => (deg * Math.PI) / 180;
const toDeg = (rad: number) => (rad * 180) / Math.PI;

export function viewAzimuthDeg(id: CameraViewId): number {
  return CAMERA_VIEWS.find((v) => v.id === id)?.azimuthDeg ?? 0;
}

/** Field of view, in degrees, of a lens across the given sensor width. */
export function lensToFovDeg(lensMm: number, sensorMm: number): number {
  return toDeg(2 * Math.atan(sensorMm / (2 * lensMm)));
}

/**
 * Vertical FOV that keeps the (square) reference framing on the viewport's shorter side, so the
 * whole character stays visible in both landscape and portrait viewports.
 */
export function verticalFovDeg(fovDeg: number, aspect: number): number {
  if (aspect >= 1) return fovDeg;
  return toDeg(2 * Math.atan(Math.tan(toRad(fovDeg) / 2) / aspect));
}

/**
 * The azimuth the character faces, from the horizontal offset of its face (eyes) relative to the
 * centre of its body, snapped to the nearest quarter turn because the asset is authored
 * axis-aligned. Returns null when the offset is too small to tell.
 */
export function facingAzimuthDeg(dx: number, dz: number): number | null {
  if (Math.hypot(dx, dz) < 1e-4) return null;
  return Math.round(toDeg(Math.atan2(dx, dz)) / 90) * 90;
}

/** Camera position for a view, in three.js world space. */
export function viewPosition(azimuthDeg: number, facingDeg = 0, distance: number = LOOKDEV_CAMERA.distance) {
  const a = toRad(azimuthDeg + facingDeg);
  const { target, height } = LOOKDEV_CAMERA;
  // Keep the reference elevation (camera height relative to the aim point) at any distance.
  const y = target.y + ((height - target.y) * distance) / LOOKDEV_CAMERA.distance;
  return { x: target.x + distance * Math.sin(a), y, z: target.z + distance * Math.cos(a) };
}
