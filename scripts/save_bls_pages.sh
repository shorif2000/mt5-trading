#!/usr/bin/env bash
# Save the official BLS release pages yourself, in your own Chrome browser.
#
# BLS blocks automated downloads, so this script does NOT download anything. It opens each
# official page in Google Chrome for you, waits while you save it, then checks the saved file
# (not an "Access Denied" page, the expected title is present) and records its sha256 and the
# time you saved it in data/calendar/raw/bls/MANIFEST.tsv.
#
#   bash scripts/save_bls_pages.sh
#
# For each page:  in Chrome press Cmd+S, choose Format "Webpage, HTML Only", save it into
# data/calendar/raw/bls/ under the exact file name shown, then press Enter here.
# Afterwards run:  uv run python scripts/build_economic_calendar.py

set -euo pipefail

cd "$(dirname "$0")/.."
DEST="data/calendar/raw/bls"
MANIFEST="$DEST/MANIFEST.tsv"
mkdir -p "$DEST"

# file name | official URL | text that must appear on the genuine page
PAGES=(
  "cpi_schedule.html|https://www.bls.gov/schedule/news_release/cpi.htm|Consumer Price Index"
  "empsit_schedule.html|https://www.bls.gov/schedule/news_release/empsit.htm|Employment Situation"
  "cpi_archive.html|https://www.bls.gov/bls/news-release/cpi.htm|Consumer Price Index"
  "empsit_archive.html|https://www.bls.gov/bls/news-release/empsit.htm|Employment Situation"
)

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This helper opens Chrome with macOS 'open'. On other systems, open each URL below" >&2
  echo "in Chrome yourself and save it under the file name shown." >&2
fi

printf 'file\turl\tsha256\tbytes\tsaved_utc\tverified_utc\n' > "$MANIFEST.tmp"
failed=0
for entry in "${PAGES[@]}"; do
  IFS='|' read -r name url marker <<< "$entry"
  path="$DEST/$name"
  echo
  echo "== $name"
  echo "   $url"
  if [[ "$(uname)" == "Darwin" ]]; then
    open -a "Google Chrome" "$url"
  fi
  echo "   In Chrome: Cmd+S -> Format 'Webpage, HTML Only' -> save as:"
  echo "   $(pwd)/$path"
  read -r -p "   Press Enter when saved (or type 'skip'): " answer
  if [[ "$answer" == "skip" ]]; then
    echo "   skipped"
    failed=1
    continue
  fi
  if [[ ! -s "$path" ]]; then
    echo "   NOT FOUND: $path" >&2
    failed=1
    continue
  fi
  if grep -qi "Access Denied" "$path"; then
    echo "   REJECTED: the saved file is an 'Access Denied' page; reload in Chrome and save again" >&2
    failed=1
    continue
  fi
  if ! grep -q "$marker" "$path"; then
    echo "   REJECTED: '$marker' not found; is this the right page?" >&2
    failed=1
    continue
  fi
  sha=$(shasum -a 256 "$path" | cut -d' ' -f1)
  bytes=$(wc -c < "$path" | tr -d ' ')
  saved=$(date -u -r "$path" +%Y-%m-%dT%H:%M:%SZ)
  verified=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$sha" "$bytes" "$saved" "$verified" \
    >> "$MANIFEST.tmp"
  echo "   ok  sha256 ${sha:0:16}…  ($bytes bytes)"
done
mv "$MANIFEST.tmp" "$MANIFEST"

echo
if [[ $failed -ne 0 ]]; then
  echo "Some pages are missing or invalid; re-run this script for them." >&2
  exit 1
fi
echo "All pages saved and checked. Next: uv run python scripts/build_economic_calendar.py"
