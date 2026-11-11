#!/usr/bin/env bash
# Download the archived BLS CPI and Employment Situation release documents (2022-11 onwards)
# with curl, identifying yourself as BLS asks automated clients to: a User-Agent naming this
# tool and a contact email address. It does NOT disguise itself as a browser. If BLS still
# refuses (HTTP 403), save the pages in Chrome instead.
#
#   bash scripts/download_bls_releases.sh            # asks for your contact email
#   BLS_CONTACT=you@example.com bash scripts/download_bls_releases.sh
#
# The list of releases comes from the archive pages you saved with scripts/save_bls_pages.sh.
# Files go to data/calendar/raw/bls/releases/ (git-ignored) with MANIFEST.tsv (URL, sha256,
# download time). Re-running skips files already downloaded and verified. One request every
# 2 seconds. Then run:  uv run python scripts/build_economic_calendar.py

set -euo pipefail

cd "$(dirname "$0")/.."
DEST="data/calendar/raw/bls/releases"
MANIFEST="$DEST/MANIFEST.tsv"
mkdir -p "$DEST"

contact="${BLS_CONTACT:-}"
if [[ -z "$contact" ]]; then
  echo "BLS asks scripts to identify themselves with a contact email (sent to bls.gov in the"
  read -r -p "User-Agent header of each request). Your email: " contact
fi
if [[ "$contact" != *@*.* ]]; then
  echo "A contact email address is required." >&2
  exit 2
fi
AGENT="mt5-trading-research-calendar/1.0 (contact: $contact)"

# Release URLs from the saved archive pages (publication dates from 2022-11-01).
URLS=()
while IFS= read -r line; do URLS+=("$line"); done < <(uv run python - <<'PY'
from datetime import date
from pathlib import Path
from trading.research.bls_calendar import ARCHIVE_NAMES, parse_archive

for kind, page in (("cpi", "cpi_archive.html"), ("employment_situation", "empsit_archive.html")):
    html = (Path("data/calendar/raw/bls") / page).read_text(encoding="utf-8", errors="ignore")
    for day in parse_archive(html, kind):
        if day >= date(2022, 11, 1):
            print(f"https://www.bls.gov/news.release/archives/"
                  f"{ARCHIVE_NAMES[kind]}_{day:%m%d%Y}.htm")
PY
)
echo "${#URLS[@]} release documents to check."

[[ -f "$MANIFEST" ]] || printf 'file\turl\tsha256\tbytes\tdownloaded_utc\n' > "$MANIFEST"
ok=0
failed=0
for url in "${URLS[@]}"; do
  name="$(basename "$url")"
  path="$DEST/$name"
  if [[ -s "$path" ]] && grep -q "^$name	" "$MANIFEST" && grep -qi "embargoed" "$path"; then
    ok=$((ok + 1))
    continue
  fi
  status=$(curl -sS -L -A "$AGENT" -H "Accept: text/html" -o "$path.tmp" -w "%{http_code}" "$url" \
    || echo "000")
  sleep 2
  if [[ "$status" != "200" ]] || grep -qi "Access Denied" "$path.tmp"; then
    echo "  $name: HTTP $status (refused or failed)" >&2
    rm -f "$path.tmp"
    failed=$((failed + 1))
    if [[ "$status" == "403" && $failed -ge 3 && $ok -eq 0 ]]; then
      echo "BLS is refusing these requests; stop here and save the pages in Chrome instead." >&2
      exit 1
    fi
    continue
  fi
  if ! grep -qi "embargoed" "$path.tmp"; then
    echo "  $name: no embargo statement found; kept aside as $path.unexpected" >&2
    mv "$path.tmp" "$path.unexpected"
    failed=$((failed + 1))
    continue
  fi
  mv "$path.tmp" "$path"
  sha=$(shasum -a 256 "$path" | cut -d' ' -f1)
  bytes=$(wc -c < "$path" | tr -d ' ')
  grep -v "^$name	" "$MANIFEST" > "$MANIFEST.tmp" || true
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$sha" "$bytes" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >> "$MANIFEST.tmp"
  mv "$MANIFEST.tmp" "$MANIFEST"
  ok=$((ok + 1))
  echo "  $name ok"
done

echo "$ok downloaded and verified, $failed failed."
[[ $failed -eq 0 ]] || { echo "Re-run to retry the failed ones." >&2; exit 1; }
echo "Next: uv run python scripts/build_economic_calendar.py"
