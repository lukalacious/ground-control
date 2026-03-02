# Ground Control

Amsterdam apartment hunting dashboard powered by an Elasticsearch property API.

Scrapes listings nightly, scores them by value (price/m² vs neighbourhood and city averages), and serves an interactive dashboard with map view, neighbourhood filtering, and price drop tracking.

## Stack

- **Scraper**: Python + curl_cffi (TLS fingerprinting) hitting the property search API
- **Database**: SQLite — listings, price history, neighbourhood stats
- **Dashboard**: Self-contained HTML with Leaflet map, filters, and scoring
- **Serving**: Python HTTP server + Tailscale Serve

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Full scrape
python3 scraper.py --city amsterdam --type buy --property-type apartment --db ground_control.db

# Delta scrape (only new/changed)
python3 scraper.py --city amsterdam --type buy --property-type apartment --delta --db ground_control.db

# Generate dashboard
python3 generate_dashboard.py --db ground_control.db --output ground_control_dashboard.html

# Open in browser
python3 generate_dashboard.py --db ground_control.db --output ground_control_dashboard.html --open
```

## Nightly automation

`run_nightly.sh` runs the full scrape, geocodes new neighbourhoods, and regenerates the dashboard. Scheduled via `com.groundcontrol.scraper.plist` (macOS LaunchAgent, 6AM daily).

## Scoring

Each listing gets a composite score based on:
- Price per m² vs neighbourhood average (40%)
- Price per m² vs city average (30%)
- Days on market (30%)
