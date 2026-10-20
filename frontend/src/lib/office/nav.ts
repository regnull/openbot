/**
 * Navigation over the office's authored waypoint graph (office-layout-v01.json, nav.edges).
 *
 * Edges were checked at build time for line of sight at the layout's clearance radius;
 * the same obstacle geometry is used here to connect a free start position to the graph and
 * to smooth routes (string pulling), so an Openling never cuts through a wall, desk or plant.
 * Seats and work spots are not graph nodes: a route ends at their approach point and the
 * final short "interaction move" is done by the actor.
 */
import type { LayoutIndex, Obstacle, OfficeAnchor, Vec2 } from "./layout";

export const APPROACH_SUFFIX = "__approach";

// ------------------------------------------------------------------ geometry
export function segPointDist(ax: number, az: number, bx: number, bz: number, px: number, pz: number): number {
  const vx = bx - ax, vz = bz - az;
  const l2 = vx * vx + vz * vz;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * vx + (pz - az) * vz) / l2));
  return Math.hypot(ax + vx * t - px, az + vz * t - pz);
}

function cross(o: Vec2, p: Vec2, q: Vec2) {
  return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0]);
}

export function segSegDist(a: Vec2, b: Vec2, c: Vec2, d: Vec2): number {
  const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
  if ((d1 > 0) !== (d2 > 0) && (d3 > 0) !== (d4 > 0)) return 0;
  return Math.min(
    segPointDist(a[0], a[1], b[0], b[1], c[0], c[1]), segPointDist(a[0], a[1], b[0], b[1], d[0], d[1]),
    segPointDist(c[0], c[1], d[0], d[1], a[0], a[1]), segPointDist(c[0], c[1], d[0], d[1], b[0], b[1]),
  );
}

/** Distance between segment a-b and an obstacle's surface (0 when they touch or overlap). */
export function obstacleDist(o: Obstacle, a: Vec2, b: Vec2): number {
  if (o.kind === "circle") return Math.max(0, segPointDist(a[0], a[1], b[0], b[1], o.center[0], o.center[1]) - o.radius);
  if (o.kind === "segment") return Math.max(0, segSegDist(a, b, o.a, o.b) - o.halfWidth);
  const c = Math.cos(o.yaw), s = Math.sin(o.yaw);
  const loc = (p: Vec2): Vec2 => {
    const dx = p[0] - o.center[0], dz = p[1] - o.center[1];
    return [dx * c - dz * s, dx * s + dz * c];
  };
  const la = loc(a), lb = loc(b);
  const hw = o.size[0] / 2, hd = o.size[1] / 2;
  const inside = (p: Vec2) => Math.abs(p[0]) <= hw && Math.abs(p[1]) <= hd;
  if (inside(la) || inside(lb)) return 0;
  const k: Vec2[] = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
  return Math.min(...k.map((p, i) => segSegDist(la, lb, p, k[(i + 1) % 4])));
}

export interface Route {
  /** Ground points from the start to the goal (the anchor, or its approach point). */
  points: Vec2[];
  length: number;
  /** Graph nodes visited (for debugging and tests). */
  nodes: string[];
  goal: string;
}

interface Edge { to: string; cost: number }

export class NavGraph {
  readonly nodes = new Map<string, Vec2>();
  private readonly adj = new Map<string, Edge[]>();
  private readonly ignoreFor = new Map<string, Set<string>>();
  readonly clearance: number;
  private readonly index: LayoutIndex;
  private readonly obstacles: Obstacle[];

  constructor(index: LayoutIndex) {
    this.index = index;
    const L = index.layout;
    this.clearance = L.clearance;
    this.obstacles = L.obstacles;
    for (const w of L.nav.waypoints) this.nodes.set(w.id, [w.position[0], w.position[2]]);
    for (const a of L.anchors) {
      if (a.alias) continue;
      if (a.approach) {
        const id = a.id + APPROACH_SUFFIX;
        this.nodes.set(id, [a.approach[0], a.approach[2]]);
        this.ignoreFor.set(id, new Set(a.ignore ?? []));
      } else if (a.kind === "stand" || a.kind === "approach") {
        this.nodes.set(a.id, [a.position[0], a.position[2]]);
      }
    }
    for (const [a, b, cost] of L.nav.edges) {
      if (!this.nodes.has(a) || !this.nodes.has(b)) continue;
      this.link(a, b, cost);
    }
  }

  private link(a: string, b: string, cost: number) {
    (this.adj.get(a) ?? this.adj.set(a, []).get(a)!).push({ to: b, cost });
    (this.adj.get(b) ?? this.adj.set(b, []).get(b)!).push({ to: a, cost });
  }

  neighbors(id: string): readonly Edge[] {
    return this.adj.get(id) ?? [];
  }

  /** Line of sight between two ground points with `r` metres of clearance from every obstacle. */
  clear(a: Vec2, b: Vec2, r = this.clearance, ignore?: Set<string>): boolean {
    for (const o of this.obstacles) {
      if (ignore?.has(o.source)) continue;
      if (obstacleDist(o, a, b) < r) return false;
    }
    return true;
  }

  /** Smallest distance from a point to any obstacle surface. */
  freeRadius(p: Vec2): number {
    let m = Infinity;
    for (const o of this.obstacles) m = Math.min(m, obstacleDist(o, p, p));
    return m;
  }

  /** Graph node of an anchor (its approach node if it has one). */
  goalNode(anchor: OfficeAnchor): string {
    const a = anchor.alias ? this.index.anchor(anchor.alias) : anchor.seat ? this.index.anchor(anchor.seat) : anchor;
    return a.approach ? a.id + APPROACH_SUFFIX : a.id;
  }

  /** Node at (almost) exactly this point, if any. */
  nodeAt(p: Vec2, tol = 0.04): string | null {
    for (const [id, q] of this.nodes) if (Math.abs(q[0] - p[0]) < tol && Math.abs(q[1] - p[1]) < tol) return id;
    return null;
  }

  /** Plans a walk from a free ground point to an anchor's node. */
  route(from: Vec2, anchorId: string): Route | null {
    const goal = this.goalNode(this.index.anchor(anchorId));
    return this.routeToNode(from, goal);
  }

  routeToNode(from: Vec2, goal: string): Route | null {
    const goalPos = this.nodes.get(goal);
    if (!goalPos) return null;
    const startNode = this.nodeAt(from);
    // temporary start links: visible nodes, relaxing the clearance if the start is tight
    const startLinks: Edge[] = [];
    if (startNode) {
      startLinks.push({ to: startNode, cost: 0 });
    } else {
      for (const r of [this.clearance, 0.22, 0.12]) {
        for (const [id, p] of this.nodes) {
          const d = Math.hypot(p[0] - from[0], p[1] - from[1]);
          if (d > 4.2) continue;
          if (this.clear(from, p, r, this.ignoreFor.get(id))) startLinks.push({ to: id, cost: d });
        }
        if (startLinks.length) break;
      }
      if (!startLinks.length) {
        let best = "", bd = Infinity;
        for (const [id, p] of this.nodes) {
          const d = Math.hypot(p[0] - from[0], p[1] - from[1]);
          if (d < bd) { bd = d; best = id; }
        }
        startLinks.push({ to: best, cost: bd });
      }
    }
    // A*
    const START = "__start__";
    const h = (id: string) => {
      const p = this.nodes.get(id)!;
      return Math.hypot(p[0] - goalPos[0], p[1] - goalPos[1]);
    };
    const g = new Map<string, number>([[START, 0]]);
    const came = new Map<string, string>();
    const open = new Set<string>([START]);
    const f = new Map<string, number>([[START, Math.hypot(from[0] - goalPos[0], from[1] - goalPos[1])]]);
    while (open.size) {
      let cur = "", best = Infinity;
      for (const n of open) { const v = f.get(n) ?? Infinity; if (v < best) { best = v; cur = n; } }
      if (cur === goal) break;
      open.delete(cur);
      const edges = cur === START ? startLinks : this.neighbors(cur);
      for (const e of edges) {
        // approach points may brush their own seat: they start or end routes, they never carry them
        if (cur !== START && e.to !== goal && e.to.endsWith(APPROACH_SUFFIX)) continue;
        const t = (g.get(cur) ?? Infinity) + e.cost;
        if (t < (g.get(e.to) ?? Infinity)) {
          came.set(e.to, cur);
          g.set(e.to, t);
          f.set(e.to, t + h(e.to));
          open.add(e.to);
        }
      }
    }
    if (!g.has(goal)) return null;
    const nodes: string[] = [];
    for (let n: string | undefined = goal; n && n !== START; n = came.get(n)) nodes.unshift(n);
    const raw: Vec2[] = [from, ...nodes.map((n) => this.nodes.get(n)!)];
    // drop a duplicate first point (start exactly on a node)
    if (raw.length > 1 && Math.hypot(raw[0][0] - raw[1][0], raw[0][1] - raw[1][1]) < 1e-3) raw.shift();
    const points = this.smooth(raw, nodes[nodes.length - 1]);
    let length = 0;
    for (let i = 1; i < points.length; i++) length += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    return { points, length, nodes, goal };
  }

  /** String pulling: skip intermediate points while the shortcut keeps full clearance. */
  private smooth(pts: Vec2[], goal: string): Vec2[] {
    if (pts.length <= 2) return pts;
    const out: Vec2[] = [pts[0]];
    const ignoreGoal = this.ignoreFor.get(goal);
    let i = 0;
    while (i < pts.length - 1) {
      let j = pts.length - 1;
      for (; j > i + 1; j--) {
        const ign = j === pts.length - 1 ? ignoreGoal : undefined;
        if (this.clear(pts[i], pts[j], this.clearance, ign)) break;
      }
      out.push(pts[j]);
      i = j;
    }
    return out;
  }
}
