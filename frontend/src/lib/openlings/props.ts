/**
 * The 13 Openling props in openling-props-v01.glb and where each one may go.
 *
 * Frames (three.js, Y up): every socket is used through a "socket frame" that equals the
 * character frame in the bind pose (X = the character's left, Y = up, Z = the way it
 * faces) and then follows its bone. Worn props were modelled in place on the real head
 * relative to their socket, so their offset is the identity. Every carry grip seats the
 * prop in the mitten's thumb/palm notch: the crease on the front of the hand at
 * NOTCH_L / NOTCH_R in the hand socket frame (measured on the rigid hand mesh). Flat props are
 * held by their lower rear corner or edge and lean outward clear of the sleeve and shoe; the
 * phone points forward screen-up, the pen tip and the wrench jaw reach out of the fist.
 * Presenting grips (Reporting) keep the props in front of the chest; on the right hand the
 * edge sits in the notch, the left hand presses against the belly so its props stay in front
 * of it. Desk spots sit around the laptop on the 15 cm lab desk.
 */
import type { OpenlingClip } from "./animations";

export type PropId =
  | "bluetooth_earpiece" | "smartphone" | "square_glasses" | "round_glasses" | "laptop" | "research_goggles"
  | "cap" | "pen" | "paper_notebook" | "large_headphones" | "wrench" | "toolbox" | "tablet";

export type PropPlacement = "worn" | "heldLeft" | "heldRight" | "desk" | "floor" | "hidden";
export type PlacedMode = Exclude<PropPlacement, "hidden">;

export type SocketName =
  | "Socket_Glasses" | "Socket_Cap" | "Socket_BluetoothEarpiece" | "Socket_Headphones" | "Socket_ResearchGoggles"
  | "Socket_Hand_L" | "Socket_Hand_R" | "Socket_Back" | "Socket_Chest" | "Socket_DeskInteraction" | "Root";

export const SOCKETS: readonly SocketName[] = [
  "Socket_Glasses", "Socket_Cap", "Socket_BluetoothEarpiece", "Socket_Headphones", "Socket_ResearchGoggles",
  "Socket_Hand_L", "Socket_Hand_R", "Socket_Back", "Socket_Chest", "Socket_DeskInteraction",
];

export interface PropTransform {
  position?: readonly [number, number, number];
  /** x, y, z, w */
  quaternion?: readonly [number, number, number, number];
}

export interface PropAttachment {
  socket: SocketName;
  /** Offset in the socket frame (for held props: the carry grip used by most clips). */
  offset?: PropTransform;
  /**
   * Grips for specific clips (e.g. presenting a tablet in Reporting). The runtime blends
   * them by the clips' crossfade weights, so a prop never jumps between grips.
   */
  clipOffsets?: Partial<Record<OpenlingClip, PropTransform>>;
}

export interface PropInfo {
  id: PropId;
  /** Root node in the props GLB. */
  node: string;
  label: string;
  tagline: string;
  category: "head" | "hand" | "desk";
  placements: Partial<Record<PlacedMode, PropAttachment>>;
  defaultPlacement: PlacedMode;
  /** Props that cannot be worn/placed at the same time as this one. */
  conflicts?: readonly PropId[];
  conflictReason?: string;
}

/** Deepest point of the thumb/palm crease of each mitten, in its Socket_Hand frame (metres). */
export const NOTCH_L: readonly [number, number, number] = [-0.003, -0.01, 0.027];
export const NOTCH_R: readonly [number, number, number] = [0.003, -0.01, 0.027];

// Lying flat on the desk, front face up (the props' fronts face +Z in their own frame).
const FLAT: PropTransform["quaternion"] = [-Math.SQRT1_2, 0, 0, Math.SQRT1_2];
const FLAT_ALONG_X: PropTransform["quaternion"] = [-0.5, -0.5, -0.5, 0.5];

export const PROPS: Record<PropId, PropInfo> = {
  bluetooth_earpiece: {
    id: "bluetooth_earpiece", node: "PROP_BluetoothEarpiece", label: "Bluetooth earpiece", tagline: "Stay connected.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_BluetoothEarpiece" } },
    conflicts: ["large_headphones", "research_goggles"],
    conflictReason: "sits where the headphone cup and the goggles strap go",
  },
  smartphone: {
    id: "smartphone", node: "PROP_Smartphone", label: "Smartphone", tagline: "Chat. Plan. Do.",
    category: "hand", defaultPlacement: "heldLeft",
    placements: {
      heldLeft: {
        socket: "Socket_Hand_L", offset: { position: [0.0062, -0.0023, 0.0755], quaternion: [-0.1098, 0.7119, 0.6408, -0.2657] },
        clipOffsets: { Reporting: { position: [0.0307, 0.0616, 0.0509], quaternion: [-0.1838, 0.8007, 0.2444, 0.5151] } },
      },
      heldRight: { socket: "Socket_Hand_R", offset: { position: [-0.0066, -0.0023, 0.0755], quaternion: [0.0877, 0.7185, 0.6441, 0.2473] } },
      desk: { socket: "Socket_DeskInteraction", offset: { position: [-0.25, 0.0065, -0.12], quaternion: FLAT } },
    },
  },
  square_glasses: {
    id: "square_glasses", node: "PROP_SquareGlasses", label: "Square glasses", tagline: "See more possibilities.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_Glasses" } },
    conflicts: ["round_glasses", "research_goggles"], conflictReason: "only one pair of eyewear at a time",
  },
  round_glasses: {
    id: "round_glasses", node: "PROP_RoundGlasses", label: "Round glasses", tagline: "Different perspectives.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_Glasses" } },
    conflicts: ["square_glasses", "research_goggles"], conflictReason: "only one pair of eyewear at a time",
  },
  laptop: {
    id: "laptop", node: "PROP_Laptop", label: "Laptop", tagline: "Build bigger ideas.",
    category: "desk", defaultPlacement: "desk",
    placements: { desk: { socket: "Socket_DeskInteraction" } },
  },
  research_goggles: {
    id: "research_goggles", node: "PROP_ResearchGoggles", label: "Research goggles", tagline: "Explore. Learn. Discover.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_ResearchGoggles" } },
    conflicts: ["square_glasses", "round_glasses", "large_headphones", "bluetooth_earpiece"],
    conflictReason: "the visor replaces glasses and its strap runs under the ear devices",
  },
  cap: {
    id: "cap", node: "PROP_Cap", label: "Cap", tagline: "Ready for what's next.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_Cap" } },
    conflicts: ["large_headphones"], conflictReason: "the headband would cross the cap's crown",
  },
  pen: {
    id: "pen", node: "PROP_Pen", label: "Pen", tagline: "Small ideas. Big impact.",
    category: "hand", defaultPlacement: "heldRight",
    placements: {
      // gripped on the barrel in the thumb/palm notch; the tip points forward and down
      heldRight: {
        socket: "Socket_Hand_R", offset: { position: [-0.0156, -0.0103, 0.068], quaternion: [-0.7023, -0.3443, 0.0557, 0.6206] },
        clipOffsets: { Reporting: { position: [-0.0391, -0.0237, 0.0583], quaternion: [-0.4622, -0.1717, -0.3996, 0.7728] } },
      },
      heldLeft: { socket: "Socket_Hand_L", offset: { position: [0.0157, -0.0097, 0.0679], quaternion: [-0.7085, 0.3242, -0.0354, 0.6259] } },
      desk: { socket: "Socket_DeskInteraction", offset: { position: [-0.17, 0.0085, 0.07], quaternion: FLAT_ALONG_X } },
    },
  },
  paper_notebook: {
    id: "paper_notebook", node: "PROP_PaperNotebook", label: "Paper notebook", tagline: "Better ideas, brighter days.",
    category: "hand", defaultPlacement: "heldLeft",
    placements: {
      heldLeft: {
        socket: "Socket_Hand_L", offset: { position: [0.0308, -0.034, 0.0928], quaternion: [0.708, 0.325, 0.6181, -0.1052] },
        clipOffsets: { Reporting: { position: [0.0469, 0.0655, 0.0737], quaternion: [-0.1971, 0.8235, 0.2536, 0.4675] } },
      },
      heldRight: {
        socket: "Socket_Hand_R", offset: { position: [0.0305, 0.0525, 0.0643], quaternion: [-0.3078, -0.7176, -0.083, 0.6192] },
        clipOffsets: { Reporting: { position: [0.0575, -0.013, 0.0743], quaternion: [-0.2732, -0.4227, -0.4434, 0.7417] } },
      },
      desk: { socket: "Socket_DeskInteraction", offset: { position: [-0.27, 0.011, 0.04], quaternion: FLAT } },
    },
  },
  large_headphones: {
    id: "large_headphones", node: "PROP_LargeHeadphones", label: "Large headphones", tagline: "Focus anywhere.",
    category: "head", defaultPlacement: "worn",
    placements: { worn: { socket: "Socket_Headphones" } },
    conflicts: ["cap", "research_goggles", "bluetooth_earpiece"],
    conflictReason: "the headband crosses the cap and the cups cover the strap and the earpiece",
  },
  wrench: {
    id: "wrench", node: "PROP_Wrench", label: "Wrench", tagline: "Fix. Improve. Keep going.",
    category: "hand", defaultPlacement: "heldRight",
    placements: {
      // the handle runs into the notch; the jaw and most of the shaft reach forward out of the fist
      heldRight: { socket: "Socket_Hand_R", offset: { position: [-0.0182, -0.0095, 0.081], quaternion: [-0.3264, 0.7057, 0.6241, -0.0767] } },
      heldLeft: { socket: "Socket_Hand_L", offset: { position: [0.0182, -0.0089, 0.081], quaternion: [0.3063, 0.7114, 0.6301, 0.0564] } },
      floor: { socket: "Root", offset: { position: [0.36, 0.007, 0.18], quaternion: FLAT_ALONG_X } },
    },
  },
  toolbox: {
    id: "toolbox", node: "PROP_Toolbox", label: "Toolbox", tagline: "Tools for a brighter tomorrow.",
    category: "hand", defaultPlacement: "heldLeft",
    placements: {
      heldLeft: { socket: "Socket_Hand_L", offset: { position: [-0.0078, 0.0104, -0.0007], quaternion: [-0.3757, 0.6575, 0.324, 0.5671] } },
      heldRight: { socket: "Socket_Hand_R", offset: { position: [0.0077, 0.0104, -0.0007], quaternion: [0.3213, 0.5697, -0.3716, 0.6589] } },
      // origin is the handle grip; the box is 18.5 cm tall below it
      floor: { socket: "Root", offset: { position: [0.42, 0.185, 0.02], quaternion: [0, Math.SQRT1_2, 0, Math.SQRT1_2] } },
    },
  },
  tablet: {
    id: "tablet", node: "PROP_Tablet", label: "Tablet", tagline: "Capture. Organize. Share.",
    category: "hand", defaultPlacement: "heldLeft",
    placements: {
      heldLeft: {
        socket: "Socket_Hand_L", offset: { position: [0.0257, -0.0164, 0.1186], quaternion: [0.708, 0.325, 0.6181, -0.1052] },
        clipOffsets: { Reporting: { position: [0.0507, 0.0572, 0.1031], quaternion: [-0.1984, 0.8321, 0.2519, 0.4525] } },
      },
      heldRight: {
        socket: "Socket_Hand_R", offset: { position: [0.0238, 0.0547, 0.0951], quaternion: [-0.3078, -0.7176, -0.083, 0.6192] },
        clipOffsets: { Reporting: { position: [0.0627, -0.0253, 0.1039], quaternion: [-0.2792, -0.4363, -0.4413, 0.7328] } },
      },
      desk: { socket: "Socket_DeskInteraction", offset: { position: [0.29, 0.0055, 0.0], quaternion: FLAT } },
    },
  },
};

export const PROP_IDS = Object.keys(PROPS) as PropId[];

/** Which props are where on one Openling. A prop appears at most once. */
export type Loadout = Partial<Record<PropId, PlacedMode>>;

export interface LoadoutChange {
  loadout: Loadout;
  /** Props taken off to make room, with the reason. */
  removed: { id: PropId; reason: string }[];
}

/**
 * Puts `id` at `placement` (or removes it with "hidden"), resolving conflicts: an occupied
 * hand is emptied, eyewear replaces eyewear, and props that cannot be worn together come
 * off. Rejects placements the prop does not support.
 */
export function placeProp(current: Loadout, id: PropId, placement: PropPlacement): LoadoutChange {
  const next: Loadout = { ...current };
  const removed: LoadoutChange["removed"] = [];
  if (placement === "hidden") {
    delete next[id];
    return { loadout: next, removed };
  }
  const info = PROPS[id];
  if (!info.placements[placement]) throw new Error(`${info.label} cannot be placed "${placement}"`);
  delete next[id];
  for (const [otherId, where] of Object.entries(next) as [PropId, PlacedMode][]) {
    if ((placement === "heldLeft" || placement === "heldRight") && where === placement) {
      delete next[otherId];
      removed.push({ id: otherId, reason: `the ${placement === "heldLeft" ? "left" : "right"} hand now holds the ${info.label.toLowerCase()}` });
    } else if (conflicts(id, otherId)) {
      delete next[otherId];
      removed.push({ id: otherId, reason: PROPS[id].conflictReason ?? PROPS[otherId].conflictReason ?? "incompatible" });
    } else if (placement === "desk" && where === "desk" && sameDeskSpot(id, otherId)) {
      delete next[otherId];
      removed.push({ id: otherId, reason: "that desk spot is taken" });
    }
  }
  next[id] = placement;
  return { loadout: next, removed };
}

export function conflicts(a: PropId, b: PropId): boolean {
  return a !== b && (!!PROPS[a].conflicts?.includes(b) || !!PROPS[b].conflicts?.includes(a));
}

function sameDeskSpot(a: PropId, b: PropId): boolean {
  const pa = PROPS[a].placements.desk?.offset?.position ?? [0, 0, 0];
  const pb = PROPS[b].placements.desk?.offset?.position ?? [0, 0, 0];
  return Math.hypot(pa[0] - pb[0], pa[2] - pb[2]) < 0.08;
}

/** Applies several placements in order (later ones win), e.g. a role preset. */
export function buildLoadout(items: readonly { id: PropId; placement: PlacedMode }[]): Loadout {
  return items.reduce<Loadout>((l, it) => placeProp(l, it.id, it.placement).loadout, {});
}

/**
 * The grip for a held prop given the clips' current blend weights: each clip contributes
 * its own grip (or the default carry grip), weighted; positions are averaged and
 * quaternions blended on one hemisphere and renormalised.
 */
export function blendGrip(
  attachment: PropAttachment,
  weights: Partial<Record<OpenlingClip, number>>,
): { position: [number, number, number]; quaternion: [number, number, number, number] } {
  const base = attachment.offset ?? {};
  const grip = (t: PropTransform) => ({
    p: (t.position ?? base.position ?? [0, 0, 0]) as readonly number[],
    q: (t.quaternion ?? base.quaternion ?? [0, 0, 0, 1]) as readonly number[],
  });
  const ref = grip(base).q;
  const p = [0, 0, 0], q = [0, 0, 0, 0];
  let total = 0;
  for (const [clip, w = 0] of Object.entries(weights) as [OpenlingClip, number][]) {
    if (w <= 0) continue;
    const g = grip(attachment.clipOffsets?.[clip] ?? base);
    const sign = g.q.reduce((s, v, i) => s + v * ref[i], 0) < 0 ? -1 : 1;
    for (let i = 0; i < 3; i++) p[i] += g.p[i] * w;
    for (let i = 0; i < 4; i++) q[i] += g.q[i] * w * sign;
    total += w;
  }
  if (total <= 0) {
    const g = grip(base);
    return { position: [g.p[0], g.p[1], g.p[2]], quaternion: [g.q[0], g.q[1], g.q[2], g.q[3]] };
  }
  const n = Math.hypot(...q);
  return { position: [p[0] / total, p[1] / total, p[2] / total], quaternion: [q[0] / n, q[1] / n, q[2] / n, q[3] / n] };
}
