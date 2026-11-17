#!/bin/bash
# Gen 5 singles 7 tiers (Ubers, OU, UU, RU, NU, PU, ZU) from
# https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays
# Usage (from project root): bash scripts/log_download_gen5.sh [output-directory]
# Re-running resumes partial downloads and skips finished files.
set -u
OUTPUT_DIR="${1:-$(dirname "$0")/../data/raw}"
mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR" || exit 1
BASE="https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays/resolve/main"

# filename|expected bytes
FILES=(
"[Gen 5] UBERS.parquet|187707194"
"[Gen 5] OU_part1.parquet|506148443"
"[Gen 5] OU_part2.parquet|440231565"
"[Gen 5] OU_part3.parquet|423391104"
"[Gen 5] UU.parquet|163747346"
"[Gen 5] RU.parquet|68440838"
"[Gen 5] NU.parquet|140471606"
"[Gen 5] PU.parquet|5465668"
"[Gen 5] ZU.parquet|3045084"
)

fail=0
for entry in "${FILES[@]}"; do
  name="${entry%|*}"; want="${entry##*|}"
  have=$(stat -f%z "$name" 2>/dev/null || stat -c%s "$name" 2>/dev/null || echo 0)
  if [ "$have" = "$want" ]; then echo "OK (already) $name"; continue; fi
  enc=$(printf '%s' "$name" | sed -e 's/\[/%5B/g' -e 's/\]/%5D/g' -e 's/ /%20/g')
  echo "Downloading $name ..."
  curl -L --fail --retry 3 -C - -o "$name" "$BASE/$enc" || true
  have=$(stat -f%z "$name" 2>/dev/null || stat -c%s "$name" 2>/dev/null || echo 0)
  if [ "$have" = "$want" ]; then echo "OK $name"; else echo "SIZE MISMATCH $name ($have / $want)"; fail=1; fi
done
[ $fail = 0 ] && echo "All 9 files downloaded." || echo "Some files failed; run the script again to resume."
