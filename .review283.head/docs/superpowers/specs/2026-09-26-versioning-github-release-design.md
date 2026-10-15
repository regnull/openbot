# Versioning and GitHub releases

## Goal

Give OpenBot desktop builds a `major.minor.build` version and a single command, `make
github-release`, that builds the Electron app for macOS and Linux and publishes it as a GitHub
release. Audience: the maintainer and a few testers, so builds are unsigned.

## Version

- `VERSION` (repo root) holds `major.minor`, edited by hand.
- The build number is one past the highest `vX.Y.N` git tag, across all major.minor values, and
  never resets (`0.1.7` then a bump to `0.2` gives `0.2.8`). No tags gives build 1.
- `frontend/scripts/version.cjs` computes it and refuses a `VERSION` that would sort below the
  latest release. The version is injected with `-c.extraMetadata.version`; no file is rewritten.
- `make electron-release` stamps local builds `<next>-dev`.
- The backend (`pyproject.toml`) version is out of scope; nothing reads it.

## `make github-release`

`scripts/github-release.sh`:

1. Checks: `git`, `node`, `pnpm`, `gh` present and `gh` authenticated; tracked files clean; on
   `main`; `HEAD == origin/main` after fetching tags; release doesn't already exist.
2. Builds from a temporary `git worktree` of `HEAD` so untracked files (e.g. `backend/secret.key`,
   which `extraResources` would otherwise bundle) never ship.
3. electron-builder: `--mac --arm64 --x64` (dmg + zip) and `--linux --x64` (AppImage), output to
   `frontend/release/vX.Y.N/`.
4. `gh release create vX.Y.N --target <sha> --generate-notes` with an unsigned-build note prepended;
   GitHub creates the tag, so a failed build leaves no tag.

`DRY_RUN=1` runs everything but publishing and downgrades the branch/sync checks to warnings.

## Out of scope

Windows (the packaged backend launcher is bash-only), code signing and notarization, CI.

## Testing

Vitest coverage for `version.cjs` (no tags, cross-minor continuation, non-release tags ignored,
malformed `VERSION`, regressing `VERSION`); a real `DRY_RUN=1` run producing all artifacts.
