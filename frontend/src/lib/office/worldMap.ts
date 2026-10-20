/**
 * A coarse, stylised land mask (longitude, latitude polygons) for the dotted globe and the
 * map screens. Hand-drawn outlines: recognisable continents, not geographic data.
 */
type LonLat = [number, number];

const LAND: LonLat[][] = [
  // North America
  [[-168, 66], [-140, 70], [-95, 72], [-75, 62], [-60, 52], [-66, 45], [-75, 35], [-81, 25], [-97, 26], [-97, 18], [-87, 15], [-83, 9],
    [-78, 8], [-90, 14], [-105, 20], [-117, 32], [-124, 40], [-125, 49], [-135, 58], [-150, 60], [-165, 60]],
  // Greenland
  [[-55, 60], [-43, 60], [-20, 70], [-20, 80], [-60, 82], [-72, 77], [-55, 70]],
  // South America
  [[-80, 8], [-62, 10], [-50, 0], [-35, -6], [-39, -15], [-48, -26], [-58, -38], [-65, -55], [-72, -50], [-75, -40], [-71, -18], [-81, -5]],
  // Europe
  [[-10, 36], [-9, 43], [-2, 44], [-5, 48], [2, 51], [8, 54], [5, 58], [12, 64], [22, 70], [30, 70], [40, 66], [42, 55], [30, 46], [28, 41],
    [22, 37], [12, 38], [5, 43], [-2, 37]],
  // British Isles
  [[-6, 50], [1, 51], [0, 54], [-3, 58], [-6, 57], [-5, 54]],
  // Africa
  [[-17, 21], [-10, 30], [-5, 36], [10, 37], [20, 32], [32, 31], [35, 28], [43, 12], [51, 12], [40, -2], [40, -15], [33, -26], [20, -35], [15, -28],
    [12, -15], [9, -1], [5, 5], [-8, 5], [-16, 12]],
  // Madagascar
  [[44, -25], [47, -25], [50, -15], [49, -12], [44, -17]],
  // Asia
  [[30, 46], [42, 55], [40, 66], [60, 70], [80, 73], [105, 78], [140, 72], [180, 68], [170, 60], [155, 59], [140, 52], [135, 42], [122, 40],
    [122, 30], [110, 20], [108, 11], [103, 1], [98, 8], [92, 22], [80, 15], [77, 8], [72, 20], [62, 25], [57, 25], [52, 30], [48, 30], [36, 36]],
  // Arabia
  [[35, 30], [48, 30], [56, 26], [59, 22], [52, 16], [43, 13], [39, 20]],
  // Japan
  [[130, 31], [140, 35], [142, 40], [141, 45], [138, 40], [132, 34]],
  // Maritime Southeast Asia
  [[95, 5], [105, -6], [115, -8], [125, -9], [120, -3], [110, 1], [100, 3]],
  // Australia
  [[114, -22], [122, -18], [130, -12], [137, -12], [142, -11], [146, -18], [153, -25], [150, -37], [141, -38], [131, -31], [115, -34]],
  // New Zealand
  [[166, -46], [174, -41], [178, -38], [175, -37], [172, -41], [167, -44]],
];

function inside(lon: number, lat: number, poly: LonLat[]): boolean {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

export function isLand(lon: number, lat: number): boolean {
  for (const p of LAND) if (inside(lon, lat, p)) return true;
  return false;
}

/** Land points on a Fibonacci sphere: unit vectors (x, y, z), y up, longitude 0 toward +z. */
export function landPoints(n = 4200): Float32Array {
  const out: number[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const a = i * golden;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    const lat = (Math.asin(y) * 180) / Math.PI;
    const lon = (Math.atan2(x, z) * 180) / Math.PI;
    if (isLand(lon, lat)) out.push(x, y, z);
  }
  return new Float32Array(out);
}
