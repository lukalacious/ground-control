#!/bin/bash
# Ground Control nightly scrape + enrich + analytics pipeline
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

source "$DIR/venv/bin/activate"

echo "=== Ground Control Nightly Run: $(date) ==="

# Step 1: Full scrape (not --delta) so mark_inactive can detect sold listings
echo "--- [1/7] Scraping listings..."
python3 "$DIR/scraper.py" \
    --city amsterdam \
    --type buy

# Step 2: Geocode any new neighbourhoods
echo "--- [2/7] Geocoding neighbourhoods..."
python3 "$DIR/geocode_neighbourhoods.py"

# Step 3: Enrich new listings with detail page metadata
# Only enriches unenriched active listings (skips already-enriched ones)
echo "--- [3/7] Enriching new listings with detail metadata..."
python3 "$DIR/detail_enricher.py"

# Step 3b: Extract erfpacht intelligence
echo "--- [4/7] Extracting erfpacht intelligence..."
python3 "$DIR/erfpacht_extractor.py"

# Step 3c: Translate descriptions
echo "--- [5/7] Translating descriptions..."
python3 "$DIR/translator.py" --limit 100

# Step 4: Recompute neighbourhood analytics
echo "--- [6/7] Computing neighbourhood analytics..."
python3 "$DIR/neighbourhood_analytics.py"

# Step 5: Train model and write predictions
echo "--- [7/7] Training price model..."
python3 "$DIR/train_model.py"

echo "=== Done: $(date) ==="
