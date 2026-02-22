#!/bin/bash
# Funda nightly scrape + dashboard generation
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

source "$DIR/venv/bin/activate"

echo "=== Funda Nightly Run: $(date) ==="

# Run delta scrape (Amsterdam, apartments, all prices)
python3 "$DIR/funda_api_scraper.py" \
    --city amsterdam \
    --type buy \
    --property-type apartment \
    --delta \
    --db "$DIR/funda.db"

# Geocode any new neighbourhoods
python3 "$DIR/geocode_neighbourhoods.py"

# Regenerate dashboard with fresh data
python3 "$DIR/generate_dashboard.py" \
    --db "$DIR/funda.db" \
    --output "$DIR/funda_dashboard.html"

echo "=== Done: $(date) ==="
