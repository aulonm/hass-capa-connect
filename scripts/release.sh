#!/usr/bin/env bash
# Create a GitHub release for the version in manifest.json, if it has none yet.
#
# Run by .github/workflows/release.yml on every push to main that touches the
# manifest. HACS reads versions from GitHub *releases* (tags alone are not
# enough), so this is what makes "0.3.1" show up as an update in HACS.
#
# - The tag is "v<version>" and points at the commit being released.
# - Release notes list the commit subjects since the previous v* tag.
# - A version with a pre-release suffix (e.g. 0.4.0-beta.1) is published as a
#   GitHub pre-release, which HACS only offers to users who opted into betas.
# - Nothing happens if the tag already exists, so re-runs are safe.
#
# Local dry run (prints what it would do, needs no token):
#   DRY_RUN=1 scripts/release.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

MANIFEST="custom_components/capa_connect/manifest.json"
VERSION="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$MANIFEST")"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]]; then
  echo "::error::manifest version '$VERSION' is not semver (X.Y.Z or X.Y.Z-suffix)" >&2
  exit 1
fi

TAG="v$VERSION"
TARGET="${GITHUB_SHA:-$(git rev-parse HEAD)}"

# Make sure all tags are present (actions/checkout fetches none by default).
git fetch --quiet --tags --force origin 2>/dev/null || true

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Tag $TAG already exists; nothing to release."
  exit 0
fi

PREV_TAG="$(git tag --list 'v*' --sort=-v:refname | head -n1 || true)"
if [[ -n "$PREV_TAG" ]]; then
  RANGE="$PREV_TAG..$TARGET"
  HEADER="Changes since $PREV_TAG:"
else
  RANGE="$TARGET"
  HEADER="Changes:"
fi

NOTES="$(mktemp)"
trap 'rm -f "$NOTES"' EXIT
{
  echo "$HEADER"
  echo
  git log --no-merges --pretty='- %s (%h)' "$RANGE"
  echo
  echo "Install or update through HACS, then restart Home Assistant."
} >"$NOTES"

PRERELEASE=()
if [[ "$VERSION" == *-* ]]; then
  PRERELEASE=(--prerelease)
fi

echo "Releasing $TAG at $TARGET${PRERELEASE:+ (pre-release)}"
if [[ -n "${DRY_RUN:-}" ]]; then
  echo "--- release notes ---"
  cat "$NOTES"
  exit 0
fi

gh release create "$TAG" \
  --target "$TARGET" \
  --title "$TAG" \
  --notes-file "$NOTES" \
  "${PRERELEASE[@]}"
