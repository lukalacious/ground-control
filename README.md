# Ground Control

ML-powered price forecasting for Amsterdam real estate. Built to identify undervalued listings as they hit the market.

## What it does

Scrapes the Amsterdam property market nightly, trains a gradient-boosted regression model on 40+ features (structural, spatial, amenity, text-derived), and predicts fair-market prices for every active listing. Listings priced below their predicted value surface as potential deals via a daily Telegram morning report and a scoring system that ranks by undervaluation.

## Model

- **Algorithm**: `HistGradientBoostingRegressor` (scikit-learn) with 5-fold cross-validation
- **Target**: log-transformed listing price
- **Features**: living area, building age, distance to city center/Zuidas, energy label, floor level, VvE costs, insulation/heating/amenity flags, NLP signals from descriptions (renovated, luxury, monument, new-build), postcode, erfpacht status, and more
- **Segments**: separate models for apartments and houses to capture different price drivers
- **Evaluation**: R², MAE, MdAPE, accuracy bands (% within 5/10/15/20% of actual)

## Pipeline

```
scraper.py          → Nightly full scrape of Amsterdam listings via property search API
detail_enricher.py  → Enriches each listing with 30+ fields from detail pages
geocode_neighbourhoods.py → Geocodes new neighbourhoods via PDOK Locatieserver
scorer.py           → Composite undervalue score (neighbourhood avg, city avg, days on market)
train_model.py      → Trains apartment + house price models, writes predictions to DB
morning_report.py   → Telegram alert with new listings, predicted prices, and map
```

Orchestrated by `run_nightly.sh` (scheduled via LaunchAgent, 6 AM daily).

## Stack

- **Scraper**: Python + curl_cffi (TLS fingerprinting)
- **ML**: scikit-learn, pandas, NumPy
- **Database**: SQLite — listings, price history, neighbourhood stats, model predictions
- **Alerts**: Telegram bot (morning report with new listing map)
- **Dashboard**: self-contained HTML with Leaflet map, filters, and model diagnostics (presentation layer only)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Full scrape
python3 scraper.py --city amsterdam --type buy --db ground_control.db

# Enrich detail metadata
python3 detail_enricher.py --db ground_control.db

# Train price model
python3 train_model.py

# Morning report (new listings with predicted prices)
python3 morning_report.py              # send via Telegram
python3 morning_report.py --dry-run    # preview locally

# Generate dashboard (optional visualization)
python3 generate_dashboard.py --db ground_control.db --output-dir public/
```
