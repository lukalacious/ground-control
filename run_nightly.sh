#!/bin/bash
# Ground Control nightly scrape + enrich + dashboard generation
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

source "$DIR/venv/bin/activate"

echo "=== Ground Control Nightly Run: $(date) ==="

# Step 1: Full scrape (not --delta) so mark_inactive can detect sold listings
echo "--- [1/4] Scraping listings..."
python3 "$DIR/scraper.py" \
    --city amsterdam \
    --type buy \
    --db "$DIR/ground_control.db"

# Step 2: Geocode any new neighbourhoods
echo "--- [2/4] Geocoding neighbourhoods..."
python3 "$DIR/geocode_neighbourhoods.py"

# Step 3: Enrich new listings with detail page metadata
# Only enriches unenriched active listings (skips already-enriched ones)
echo "--- [3/4] Enriching new listings with detail metadata..."
python3 "$DIR/detail_enricher.py" \
    --db "$DIR/ground_control.db"

# Step 4: Regenerate dashboard with fresh data
echo "--- [4/4] Generating dashboard..."
python3 "$DIR/generate_dashboard.py" \
    --db "$DIR/ground_control.db" \
    --output "$DIR/ground_control_dashboard.html"

echo "=== Done: $(date) ==="
