// Release version: major.minor come from the hand-edited VERSION file at the repo root, and the
// build number is one past the highest vX.Y.N release tag. The build number never resets, so
// bumping VERSION from 0.1 to 0.2 after v0.1.7 yields 0.2.8.
//
// CLI: `node scripts/version.cjs` prints the next release version; `--dev` appends "-dev" so a
// local build is never mistaken for a published one. Callers that need the latest tags (the
// GitHub release) fetch them first; this script only reads the local repository.
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const RELEASE_TAG = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function parseMajorMinor(text) {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(text.trim());
  if (!match) throw new Error(`VERSION must contain major.minor (e.g. 0.1), got ${JSON.stringify(text.trim())}`);
  return { major: Number(match[1]), minor: Number(match[2]) };
}

function nextVersion(versionText, tags) {
  const { major, minor } = parseMajorMinor(versionText);
  const released = tags.map((tag) => RELEASE_TAG.exec(tag)).filter(Boolean).map((m) => m.slice(1, 4).map(Number));
  const build = Math.max(0, ...released.map(([, , n]) => n)) + 1;
  const newer = released.find(([ma, mi]) => ma > major || (ma === major && mi > minor));
  if (newer) throw new Error(`VERSION ${major}.${minor} is older than the released v${newer.join(".")}`);
  return `${major}.${minor}.${build}`;
}

if (require.main === module) {
  const repoRoot = path.resolve(__dirname, "..", "..");
  const versionText = fs.readFileSync(path.join(repoRoot, "VERSION"), "utf8");
  const tags = execFileSync("git", ["tag", "--list", "v*"], { cwd: repoRoot, encoding: "utf8" }).split("\n");
  const suffix = process.argv.includes("--dev") ? "-dev" : "";
  process.stdout.write(`${nextVersion(versionText, tags)}${suffix}\n`);
}

module.exports = { nextVersion, parseMajorMinor };
