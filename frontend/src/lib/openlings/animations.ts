/**
 * The six body clips baked into base-openling-animated-v01.glb by the character's animation
 * authoring script (kept with the source assets). Every clip keys every deforming
 * bone, so crossfading between any two never passes through the wide-A bind pose.
 */
export type OpenlingClip = "Idle" | "Walk" | "Wave" | "Typing" | "Reporting" | "SitIdle";

export interface ClipInfo {
  id: OpenlingClip;
  label: string;
  /** Loops forever; one-shots return to the clip that was playing before them. */
  loop: boolean;
  /** Played on a seat (SitIdle, Typing): the lab shows the seat fixture. */
  seated: boolean;
  /** Seconds, as baked (30 fps). */
  duration: number;
}

export const CLIPS: readonly ClipInfo[] = [
  { id: "Idle", label: "Idle", loop: true, seated: false, duration: 4 },
  { id: "Walk", label: "Walk", loop: true, seated: false, duration: 0.8 },
  { id: "Wave", label: "Wave", loop: false, seated: false, duration: 2.6 },
  { id: "Typing", label: "Typing", loop: true, seated: true, duration: 2 },
  { id: "Reporting", label: "Reporting", loop: true, seated: false, duration: 3.2 },
  { id: "SitIdle", label: "Sit idle", loop: true, seated: true, duration: 4 },
];

export const CLIP_IDS = CLIPS.map((c) => c.id);
export const DEFAULT_CLIP: OpenlingClip = "Idle";

/** Root speed (m/s) that cancels the in-place Walk's stance-foot travel, from the bake. */
export const WALK_ROOT_SPEED = 0.142;

/**
 * Seat and desk the seated clips were authored against (metres, three.js Y up). The
 * seated body rests 13.4 cm above the floor (openling_animations.seat_height); the seat
 * sits 2 mm under that.
 */
export const SEAT_HEIGHT = 0.132;
export const DESK_HEIGHT = 0.15;

export function clipInfo(id: OpenlingClip): ClipInfo {
  const info = CLIPS.find((c) => c.id === id);
  if (!info) throw new Error(`Unknown Openling clip: ${id}`);
  return info;
}

/** Crossfade length: getting up or sitting down takes longer than switching gestures. */
export function crossfadeSeconds(from: OpenlingClip | null, to: OpenlingClip): number {
  if (!from) return 0;
  return clipInfo(from).seated !== clipInfo(to).seated ? 0.6 : 0.35;
}

/** The clip a one-shot hands back to: the loop that was playing, else Idle (or SitIdle when seated). */
export function returnClip(oneShot: OpenlingClip, previous: OpenlingClip | null): OpenlingClip {
  if (previous && previous !== oneShot && clipInfo(previous).loop) return previous;
  return clipInfo(oneShot).seated ? "SitIdle" : DEFAULT_CLIP;
}
