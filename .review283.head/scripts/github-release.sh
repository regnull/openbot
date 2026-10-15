#!/usr/bin/env bash
# Builds the desktop app for macOS (arm64 + x64), Linux (x64) and Windows (x64) and publishes it as
# a GitHub release tagged v<major.minor.build> (see frontend/scripts/version.cjs). Builds are unsigned.
#
# The build runs in a throwaway `git worktree` of HEAD, never the working copy: electron-builder
# bundles all of backend/, and a working copy can hold untracked secrets (backend/secret.key)
# that must not end up in a public download.
#
# DRY_RUN=1 builds everything but publishes nothing, and tolerates running off an unpushed branch.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
case "${DRY_RUN:-}" in ""|0|false) DRY_RUN="" ;; *) DRY_RUN=1 ;; esac

die() { echo "github-release: $*" >&2; exit 1; }
# Hard failures for a real release, warnings for a dry run.
check() { if [[ -n "$DRY_RUN" ]]; then echo "github-release: warning: $*" >&2; else die "$*"; fi; }

for tool in git node pnpm gh; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required"
done
if [[ -z "$DRY_RUN" ]]; then
  gh auth status >/dev/null 2>&1 || die "gh is not logged in; run: gh auth login"
fi

# Intentional A && B || C: die only when either git diff found uncommitted changes.
# shellcheck disable=SC2015
git diff --quiet && git diff --cached --quiet || die "tracked files have uncommitted changes; commit or stash them first"
[[ "$(git symbolic-ref --quiet --short HEAD || true)" == main ]] || check "releases are cut from main"
git fetch --quiet --tags origin main
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] || check "HEAD is not origin/main; pull or push first"
# The next version is computed from the tags, so releasing an already released commit again would
# publish the same build under a new number.
RELEASED="$(git tag --points-at HEAD --list 'v*' | grep -E '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' | tr '\n' ' ' || true)"
[[ -z "$RELEASED" ]] || check "HEAD is already released as ${RELEASED% }; commit something new before releasing again"

VERSION="$(node frontend/scripts/version.cjs)"
TAG="v$VERSION"
SHA="$(git rev-parse HEAD)"
if [[ -z "$DRY_RUN" ]] && gh release view "$TAG" >/dev/null 2>&1; then
  die "release $TAG already exists"
fi
echo "github-release: building OpenBot $VERSION from $SHA"

OUT="$REPO_ROOT/frontend/release/$TAG"
WORK="$(mktemp -d)"
cleanup() { git -C "$REPO_ROOT" worktree remove --force "$WORK/openbot" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
git worktree add --quiet --detach "$WORK/openbot" "$SHA"
rm -rf "$OUT"

(
  cd "$WORK/openbot/frontend"
  pnpm install --frozen-lockfile
  pnpm build
  builder=(pnpm exec electron-builder --config ../electron-builder.yml --publish never
    "-c.extraMetadata.version=$VERSION" "-c.directories.output=$OUT")
  "${builder[@]}" --mac --arm64 --x64
  "${builder[@]}" --linux --x64
  "${builder[@]}" --win --x64
)

shopt -s nullglob
ASSETS=("$OUT"/*.dmg "$OUT"/*.zip "$OUT"/*.AppImage "$OUT"/*.exe)
(( ${#ASSETS[@]} > 0 )) || die "no build artifacts found in $OUT"

if [[ -n "$DRY_RUN" ]]; then
  echo "github-release: dry run; $TAG not published. Artifacts:"
  printf '  %s\n' "${ASSETS[@]}"
  exit 0
fi

NOTES="These builds are unsigned. On macOS, right-click OpenBot.app and choose Open the first time, \
or run \`xattr -dr com.apple.quarantine /Applications/OpenBot.app\`. On Linux, \`chmod +x\` the \
AppImage. On Windows, SmartScreen warns about the unsigned installer: choose More info, then Run \
anyway. The app needs [uv](https://docs.astral.sh/uv/) installed to run its bundled backend."
# GitHub creates the tag at $SHA as part of the release, so a failed build never leaves a stray tag.
gh release create "$TAG" "${ASSETS[@]}" --target "$SHA" --title "OpenBot $VERSION" --notes "$NOTES" --generate-notes
git fetch --quiet --tags origin
