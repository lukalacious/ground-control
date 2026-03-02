#!/bin/bash
# Ground Control nightly scrape + dashboard generation
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

source "$DIR/venv/bin/activate"

echo "=== Ground Control Nightly Run: $(date) ==="

# Run full scrape (not --delta) so mark_inactive can detect sold listings
python3 "$DIR/scraper.py" \
    --city amsterdam \
    --type buy \
    --property-type apartment \
    --db "$DIR/ground_control.db"

# Geocode any new neighbourhoods
python3 "$DIR/geocode_neighbourhoods.py"

# Regenerate dashboard with fresh data
python3 "$DIR/generate_dashboard.py" \
    --db "$DIR/ground_control.db" \
    --output "$DIR/ground_control_dashboard.html"

echo "=== Done: $(date) ==="
