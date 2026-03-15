#!/usr/bin/env python3
"""Generate a standalone HTML dashboard for model performance analysis.

Outputs:
  model_dashboard.html — Standalone HTML with inline CSS/JS + Chart.js
  public/model.html    — Copy for Vercel deployment
"""

import json
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

DB_PATH = Path(__file__).parent / "ground_control.db"
APT_PKL = Path(__file__).parent / "apartment_model.pkl"
HOUSE_PKL = Path(__file__).parent / "house_model.pkl"
HISTORY_PATH = Path(__file__).parent / "model_history.jsonl"
OUTPUT_PATH = Path(__file__).parent / "model_dashboard.html"
PUBLIC_PATH = Path(__file__).parent / "public" / "model.html"


# ── Erfpacht parsing ────────────────────────────────────────────────────

def parse_erfpacht_structured(text):
    """Parse raw erfpacht text into structured fields."""
    if not text or not isinstance(text, str):
        return None

    t = text.lower()
    result = {}

    if 'eeuwigdurend afgekocht' in t or 'eeuwigdurend afkoop' in t:
        result['status'] = 'eeuwigdurend_afgekocht'
    elif 'eigen grond' in t:
        result['status'] = 'eigen_grond'
    elif 'afgekocht' in t:
        result['status'] = 'afgekocht'
    elif any(kw in t for kw in ['canon', 'erfpacht', 'tijdvak']):
        result['status'] = 'active'
    else:
        result['status'] = 'unknown'

    canon_match = re.search(
        r'(?:canon\w*\s+(?:van\s+|bedraagt\s+)?)?€\s*([\d.,]+)',
        text, re.IGNORECASE
    )
    if canon_match:
        raw = canon_match.group(1).rstrip('.,').replace('.', '').replace(',', '.')
        try:
            val = float(raw)
            if val > 100:
                result['canon_yearly'] = val
        except ValueError:
            pass

    date_match = re.search(
        r'(?:afgekocht\s+)?(?:tot(?:\s+en\s+met)?|t/m)\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
        text, re.IGNORECASE
    )
    if date_match:
        raw_date = date_match.group(1).replace('/', '-')
        try:
            dt = datetime.strptime(raw_date, '%d-%m-%Y')
            result['expiry_date'] = dt.strftime('%Y-%m-%d')
            result['years_remaining'] = round(
                (dt - datetime.now()).days / 365.25, 1
            )
        except ValueError:
            pass

    sys_match = re.search(
        r'(?:algemene\s+bepalingen\s+(?:van\s+)?(?:de\s+gemeente\s+amsterdam\s+van\s+)?)'
        r'(\d{4})',
        text, re.IGNORECASE
    )
    if sys_match:
        result['system'] = f'AB{sys_match.group(1)}'
    elif 'eeuwigdurend' in t and 'nieuw' in t:
        result['system'] = 'Eeuwigdurend (nieuw)'

    return result if result else None


# ── Data loading ────────────────────────────────────────────────────────

def load_pkl_data():
    apt = joblib.load(APT_PKL)
    house = joblib.load(HOUSE_PKL)
    return apt, house


def load_listings_with_predictions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT global_id, address, neighbourhood, price_numeric,
               predicted_price, residual, living_area, energy_label,
               detail_url, erfpacht, postcode
        FROM listings
        WHERE predicted_price IS NOT NULL
    """).fetchall()
    conn.close()

    listings = [dict(r) for r in rows]
    for l in listings:
        m = re.search(r'/detail/koop/[^/]+/(\w+)-', l.get('detail_url', '') or '')
        l['property_type'] = m.group(1) if m else 'unknown'
        pred = l.get('predicted_price')
        if pred and pred > 0:
            l['residual_pct'] = round((l['price_numeric'] - pred) / pred * 100, 2)
        else:
            l['residual_pct'] = None

    return listings


def load_model_history():
    """Load model history from JSONL file."""
    history = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text().splitlines():
            if line.strip():
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return history


def get_display_address(l):
    addr = l.get('address', '')
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    slug = re.search(r'/([^/]+)/\d+/?$', str(l.get('detail_url', '')))
    return slug.group(1).replace('-', ' ').title() if slug else '\u2014'


# ── Data computation ────────────────────────────────────────────────────

def compute_neighbourhood_errors_by_type(listings):
    """Compute neighbourhood errors for all, apt, and house views."""
    def _compute(lst):
        hoods = defaultdict(list)
        for l in lst:
            hood = l.get('neighbourhood')
            if hood and l['residual_pct'] is not None:
                hoods[hood].append(l['residual_pct'])
        results = []
        for hood, residuals in hoods.items():
            if len(residuals) >= 5:
                arr = np.array(residuals)
                results.append({
                    'neighbourhood': hood,
                    'count': len(residuals),
                    'median_abs_error': round(float(np.median(np.abs(arr))), 1),
                    'mean_residual': round(float(np.mean(arr)), 1),
                })
        results.sort(key=lambda x: x['median_abs_error'])
        return results

    apt = [l for l in listings if l['property_type'] == 'appartement']
    house = [l for l in listings if l['property_type'] == 'huis']
    return {
        'both': _compute(listings),
        'apt': _compute(apt),
        'house': _compute(house),
    }


def compute_residual_histograms(listings, bin_width=2, lo=-50, hi=50):
    """Compute residual histograms for all, apt, and house views."""
    bins = list(range(lo, hi + bin_width, bin_width))
    labels = [str(bins[i]) for i in range(len(bins) - 1)]

    def _bin(lst):
        counts = [0] * (len(bins) - 1)
        for l in lst:
            r = l.get('residual_pct')
            if r is None:
                continue
            r = max(lo, min(hi - 0.01, r))
            idx = min(int((r - lo) / bin_width), len(counts) - 1)
            counts[idx] += 1
        return counts

    apt = [l for l in listings if l['property_type'] == 'appartement']
    house = [l for l in listings if l['property_type'] == 'huis']
    return {
        'labels': labels,
        'both': _bin(listings),
        'apt': _bin(apt),
        'house': _bin(house),
    }


def compute_scatter_data(listings):
    """Compute scatter data for all three views."""
    def _scatter(lst, limit=2000):
        points = []
        for l in lst[:limit]:
            err = abs(l['residual_pct']) if l['residual_pct'] is not None else 0
            if err < 5:
                color = '#6aad7a'
            elif err < 15:
                color = '#c49a6c'
            elif err < 30:
                color = '#d4873e'
            else:
                color = '#c45050'
            points.append({
                'x': round(l['predicted_price']),
                'y': round(l['price_numeric']),
                'addr': get_display_address(l)[:50],
                'err': round(err, 1),
                'color': color,
            })
        return points

    apt = [l for l in listings if l['property_type'] == 'appartement']
    house = [l for l in listings if l['property_type'] == 'huis']
    return {
        'both': {'apt': _scatter(apt), 'house': _scatter(house)},
        'apt': {'apt': _scatter(apt), 'house': []},
        'house': {'apt': [], 'house': _scatter(house)},
    }


def compute_valued_listings(listings):
    """Compute undervalued/overvalued for all three views."""
    def _compute(lst, n=15):
        with_pct = [l for l in lst if l['residual_pct'] is not None]
        with_pct.sort(key=lambda x: x['residual_pct'])
        undervalued = with_pct[:n]
        overvalued = list(reversed(with_pct[-n:]))

        def _row(l):
            url = l.get('detail_url', '')
            return {
                'addr': get_display_address(l),
                'url': f'https://www.funda.nl{url}' if url.startswith('/') else url,
                'hood': l.get('neighbourhood', '\u2014') or '\u2014',
                'price': round(l.get('price_numeric', 0)),
                'pred': round(l.get('predicted_price', 0)),
                'diff': round(l.get('residual_pct', 0), 1),
                'area': l.get('living_area'),
                'energy': l.get('energy_label', '\u2014') or '\u2014',
            }
        return [_row(l) for l in undervalued], [_row(l) for l in overvalued]

    apt = [l for l in listings if l['property_type'] == 'appartement']
    house = [l for l in listings if l['property_type'] == 'huis']
    all_under, all_over = _compute(listings)
    apt_under, apt_over = _compute(apt)
    house_under, house_over = _compute(house)
    return {
        'both': {'undervalued': all_under, 'overvalued': all_over},
        'apt': {'undervalued': apt_under, 'overvalued': apt_over},
        'house': {'undervalued': house_under, 'overvalued': house_over},
    }


def parse_all_erfpacht(listings):
    results = []
    status_counts = {}
    for l in listings:
        parsed = parse_erfpacht_structured(l.get('erfpacht'))
        if parsed:
            parsed['global_id'] = l['global_id']
            parsed['address'] = l.get('address', '')
            parsed['neighbourhood'] = l.get('neighbourhood', '')
            parsed['detail_url'] = l.get('detail_url', '')
            parsed['price_numeric'] = l.get('price_numeric')
            results.append(parsed)
            s = parsed.get('status', 'unknown')
            status_counts[s] = status_counts.get(s, 0) + 1
    return results, status_counts


def prepare_feature_importance_data(apt_data, house_data):
    """Prepare feature importance data for top 15 features per model."""
    def _top(data, n=15):
        features = data.get('features', [])
        importances = data.get('feature_importances', [])
        if not importances:
            return {'labels': [], 'values': []}
        paired = sorted(zip(features, importances), key=lambda x: x[1], reverse=True)[:n]
        paired.reverse()  # ascending for horizontal bar chart
        return {
            'labels': [p[0] for p in paired],
            'values': [round(p[1], 4) for p in paired],
        }
    return {
        'apt': _top(apt_data),
        'house': _top(house_data),
    }


def prepare_history_data(history):
    """Prepare history data for the date selector chart."""
    entries = []
    for h in history:
        ts = h.get('trained_at', '')
        try:
            dt = datetime.fromisoformat(ts)
            date_str = dt.strftime('%Y-%m-%d %H:%M')
        except (ValueError, TypeError):
            date_str = ts[:16] if ts else '?'

        apt_m = h.get('apartment', {}).get('metrics', {})
        house_m = h.get('house', {}).get('metrics', {})
        entries.append({
            'date': date_str,
            'trained_at': ts,
            'hyperparams': h.get('hyperparams', {}),
            'apt': {
                'n': h.get('apartment', {}).get('n_samples', 0),
                'r2': apt_m.get('r2', 0),
                'mae': apt_m.get('mae', 0),
                'mdape': apt_m.get('mdape', 0),
                'mape': apt_m.get('mape'),
                'rmse': apt_m.get('rmse'),
                'accuracy_bands': apt_m.get('accuracy_bands'),
                'n_features': len(h.get('apartment', {}).get('features', [])),
            },
            'house': {
                'n': h.get('house', {}).get('n_samples', 0),
                'r2': house_m.get('r2', 0),
                'mae': house_m.get('mae', 0),
                'mdape': house_m.get('mdape', 0),
                'mape': house_m.get('mape'),
                'rmse': house_m.get('rmse'),
                'accuracy_bands': house_m.get('accuracy_bands'),
                'n_features': len(h.get('house', {}).get('features', [])),
            },
        })
    return entries


# ── HTML generation ─────────────────────────────────────────────────────

def fmt_ts(ts):
    if not ts or ts == '\u2014':
        return '\u2014'
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime('%d %b %Y %H:%M UTC')
    except (ValueError, TypeError):
        return str(ts)


def build_erfpacht_html(erfpacht_parsed, erfpacht_status_counts):
    """Build the erfpacht section (not toggled)."""
    erfpacht_status_json = json.dumps(erfpacht_status_counts)
    expiring_soon = sum(
        1 for e in erfpacht_parsed
        if e.get('years_remaining') is not None and e['years_remaining'] < 10
    )

    active_erfpacht = [
        e for e in erfpacht_parsed
        if e.get('status') == 'active' or e.get('canon_yearly')
    ]
    active_erfpacht.sort(key=lambda x: x.get('canon_yearly', 0), reverse=True)

    rows = []
    for e in active_erfpacht[:50]:
        addr = e.get('address', '') or '\u2014'
        if addr == '\u2014':
            slug = re.search(r'/([^/]+)/\d+/?$', str(e.get('detail_url', '')))
            addr = slug.group(1).replace('-', ' ').title() if slug else '\u2014'
        url = e.get('detail_url', '')
        funda_link = f'https://www.funda.nl{url}' if url.startswith('/') else url
        canon = e.get('canon_yearly')
        canon_str = f'\u20ac{canon:,.0f}/yr' if canon else '\u2014'
        expiry = e.get('expiry_date', '\u2014') or '\u2014'
        yrs = e.get('years_remaining')
        yrs_str = f'{yrs:.0f}' if yrs is not None else '\u2014'
        yrs_class = 'red' if (yrs is not None and yrs < 10) else ''
        system = e.get('system', '\u2014') or '\u2014'
        rows.append(
            f'<tr>'
            f'<td><a href="{funda_link}" target="_blank" rel="noopener">{addr[:45]}</a></td>'
            f'<td>{e.get("neighbourhood", "\u2014") or "\u2014"}</td>'
            f'<td class="num">{canon_str}</td>'
            f'<td>{expiry}</td>'
            f'<td class="num {yrs_class}">{yrs_str}</td>'
            f'<td>{system}</td>'
            f'</tr>'
        )

    return {
        'status_json': erfpacht_status_json,
        'n_parsed': len(erfpacht_parsed),
        'expiring_soon': expiring_soon,
        'rows_html': '\n'.join(rows),
    }


def build_feature_html(apt_data, house_data):
    """Build the feature list section (not toggled)."""
    apt_features = apt_data.get('features', [])
    house_features = house_data.get('features', [])
    all_features = set(apt_features + house_features)

    categories = {
        'Structural': ['living_area', 'volume_m3', 'num_rooms', 'bedrooms',
                       'num_bathrooms', 'building_age', 'outdoor_area_m2',
                       'energy_score', 'num_floors', 'floor_num'],
        'Derived': ['area_per_room', 'ceiling_height_proxy', 'vve_amount',
                    'has_balcony', 'balcony_ordinal'],
        'Location': ['loc_centrum', 'loc_water', 'loc_vrij_uitzicht',
                     'loc_woonwijk', 'loc_drukke_weg', 'loc_rustige_weg',
                     'loc_park', 'pc4_code'],
        'Amenities': ['has_alarminstallatie', 'has_airconditioning', 'has_lift',
                      'has_mechanische_ventilatie', 'has_zonnepanelen'],
        'Heating': ['has_vloerverwarming', 'has_warmtepomp',
                    'has_blokverwarming', 'has_stadsverwarming'],
        'Parking': ['has_eigen_terrein', 'has_parkeergarage'],
        'Insulation': ['is_volledig_geisoleerd', 'has_dubbel_glas'],
        'Tenure': ['is_erfpacht'],
    }

    html = ''
    for cat, feats in categories.items():
        cat_feats = [f for f in feats if f in all_features]
        if not cat_feats:
            continue
        items = []
        for f in cat_feats:
            badges = []
            if f in apt_features:
                badges.append('<span class="badge apt">Apt</span>')
            if f in house_features:
                badges.append('<span class="badge house">House</span>')
            items.append(f'<span class="feature">{f} {"".join(badges)}</span>')
        html += (
            f'<div class="feat-group">'
            f'<h4>{cat}</h4>'
            f'<div class="feat-list">{"".join(items)}</div>'
            f'</div>'
        )

    return html, len(all_features)


def build_html(apt_data, house_data, listings, erfpacht_parsed,
               erfpacht_status_counts, model_history):
    """Build the complete standalone HTML dashboard with toggle."""

    # ── Compute all view-specific data ──
    scatter_data = compute_scatter_data(listings)
    hist_data = compute_residual_histograms(listings)
    hood_data = compute_neighbourhood_errors_by_type(listings)
    valued_data = compute_valued_listings(listings)
    feat_imp_data = prepare_feature_importance_data(apt_data, house_data)
    history_entries = prepare_history_data(model_history)

    # ── Model metadata ──
    apt_metrics = apt_data.get('metrics', {})
    house_metrics = house_data.get('metrics', {})
    hyperparams = apt_data.get('hyperparams', {})

    # ── Build DASHBOARD_DATA JSON ──
    dashboard_data = {
        'scatter': scatter_data,
        'hist': hist_data,
        'hoods': hood_data,
        'valued': valued_data,
        'feat_imp': feat_imp_data,
        'models': {
            'apt': {
                'metrics': apt_metrics,
                'n_samples': apt_data.get('n_samples', 0),
                'trained_at': fmt_ts(apt_data.get('trained_at', '')),
            },
            'house': {
                'metrics': house_metrics,
                'n_samples': house_data.get('n_samples', 0),
                'trained_at': fmt_ts(house_data.get('trained_at', '')),
            },
        },
        'history': history_entries,
    }

    dashboard_json = json.dumps(dashboard_data, default=str)

    # ── Non-toggled sections ──
    erfpacht = build_erfpacht_html(erfpacht_parsed, erfpacht_status_counts)
    feature_html, n_features = build_feature_html(apt_data, house_data)

    hp_rows = '\n'.join(
        f'<tr><td>{k}</td><td class="num">{v}</td></tr>'
        for k, v in hyperparams.items()
    )

    generated_at = datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ground Control \u2014 Model Performance</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #08090d; color: #c8c4be; line-height: 1.5;
    padding: 16px; max-width: 1200px; margin: 0 auto;
}}
h1 {{ color: #c49a6c; font-size: 24px; margin-bottom: 4px; }}
h2 {{ color: #c49a6c; font-size: 18px; margin: 32px 0 12px; }}
h3 {{ color: #9a8a7a; font-size: 15px; margin: 16px 0 8px; }}
h4 {{ color: #9a8a7a; font-size: 13px; margin-bottom: 6px; }}
.subtitle {{ color: #5a5650; font-size: 13px; margin-bottom: 16px; }}
a {{ color: #c49a6c; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* Segmented toggle */
.seg-toggle {{
    display: inline-flex; background: #111318; border: 1px solid #1a1c24;
    border-radius: 8px; overflow: hidden; margin-bottom: 24px;
}}
.seg-btn {{
    padding: 8px 20px; font-size: 13px; font-weight: 600;
    color: #5a5650; background: transparent; border: none;
    cursor: pointer; transition: all 0.2s;
}}
.seg-btn:hover {{ color: #c8c4be; }}
.seg-btn.active {{
    background: #c49a6c; color: #08090d; border-radius: 6px;
}}

/* Cards grid */
.cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px; }}
.card {{
    background: #111318; border: 1px solid #1a1c24; border-radius: 10px;
    padding: 16px;
}}
.card h3 {{ margin: 0 0 12px; color: #c49a6c; }}
.metric {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
.metric-label {{ color: #5a5650; font-size: 13px; }}
.metric-value {{ font-size: 15px; font-weight: 600; }}
.metric-value.big {{ font-size: 28px; color: #c49a6c; }}

/* Accuracy bars */
.acc-bar-wrap {{ margin-bottom: 8px; }}
.acc-bar-label {{
    display: flex; justify-content: space-between; font-size: 12px;
    color: #5a5650; margin-bottom: 2px;
}}
.acc-bar-label span:last-child {{ color: #c8c4be; font-weight: 600; }}
.acc-bar {{ height: 6px; background: #1a1c24; border-radius: 3px; overflow: hidden; }}
.acc-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.4s; }}

/* Tables */
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{
    text-align: left; padding: 8px 10px; color: #5a5650; font-weight: 600;
    border-bottom: 1px solid #1a1c24; cursor: pointer; white-space: nowrap;
    user-select: none;
}}
th:hover {{ color: #c49a6c; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #0e1016; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.green {{ color: #6aad7a; }}
.red {{ color: #c45050; }}
.gold {{ color: #c49a6c; }}

/* Charts */
.chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.chart-box {{
    background: #111318; border: 1px solid #1a1c24; border-radius: 10px;
    padding: 16px;
}}
.chart-box canvas {{ width: 100% !important; }}

/* Features */
.feat-group {{ margin-bottom: 12px; }}
.feat-list {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.feature {{
    background: #111318; border: 1px solid #1a1c24; border-radius: 6px;
    padding: 3px 8px; font-size: 12px; color: #9a8a7a;
}}
.badge {{
    display: inline-block; font-size: 10px; padding: 1px 4px;
    border-radius: 3px; margin-left: 4px; font-weight: 600;
}}
.badge.apt {{ background: #1a2a20; color: #6aad7a; }}
.badge.house {{ background: #2a2010; color: #c49a6c; }}

/* Misc */
.toggle-btn {{
    background: #111318; border: 1px solid #1a1c24; color: #c49a6c;
    padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px;
    margin-top: 8px;
}}
.toggle-btn:hover {{ background: #1a1c24; }}
.hidden {{ display: none; }}
.erfpacht-grid {{ display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }}

/* History selector */
.history-select {{
    background: #111318; border: 1px solid #1a1c24; color: #c8c4be;
    padding: 6px 10px; border-radius: 6px; font-size: 12px; margin-left: 12px;
}}

/* Responsive */
@media (max-width: 768px) {{
    .cards {{ grid-template-columns: 1fr; }}
    .chart-grid {{ grid-template-columns: 1fr; }}
    .erfpacht-grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 12px; }}
    .seg-btn {{ padding: 6px 12px; font-size: 12px; }}
}}
</style>
</head>
<body>

<h1>Model Performance Dashboard</h1>
<p class="subtitle">Generated {generated_at} &middot; <a href="index.html">&larr; Main Dashboard</a></p>

<!-- Segmented Toggle -->
<div class="seg-toggle" id="viewToggle">
    <button class="seg-btn active" onclick="switchView('both')">Both</button>
    <button class="seg-btn" onclick="switchView('apt')">Apartments</button>
    <button class="seg-btn" onclick="switchView('house')">Houses</button>
</div>

<!-- Summary Cards -->
<div id="summaryCards" class="cards"></div>

<!-- Accuracy Bands -->
<h2>Accuracy Bands</h2>
<div id="accuracySection" class="cards"></div>

<!-- Actual vs Predicted -->
<h2>Actual vs Predicted</h2>
<div class="chart-box">
    <canvas id="scatterChart" height="350"></canvas>
</div>

<!-- Feature Importance -->
<h2>Feature Importance</h2>
<div id="featImpSection" class="chart-grid"></div>

<!-- Per-Fold Stability -->
<h2>Per-Fold CV Stability</h2>
<div id="foldSection" class="chart-grid"></div>

<!-- Error by Price Band -->
<h2>Error by Price Band</h2>
<div class="chart-box">
    <canvas id="priceBandChart" height="250"></canvas>
</div>

<!-- Residual Distribution -->
<h2>Residual Distribution</h2>
<div class="chart-box">
    <canvas id="histResidual" height="200"></canvas>
</div>

<!-- Residual vs Predicted -->
<h2>Residual vs Predicted</h2>
<div class="chart-box">
    <canvas id="residualScatter" height="300"></canvas>
</div>

<!-- Neighbourhood Errors -->
<h2>Error by Neighbourhood</h2>
<div class="card">
    <div class="table-wrap">
        <table id="hoodTable">
            <thead>
                <tr>
                    <th onclick="sortTable('hoodTable',0)">Neighbourhood</th>
                    <th onclick="sortTable('hoodTable',1)">Count</th>
                    <th onclick="sortTable('hoodTable',2)">Median Abs Error</th>
                    <th onclick="sortTable('hoodTable',3)">Mean Residual (bias)</th>
                </tr>
            </thead>
            <tbody id="hoodBody"></tbody>
        </table>
    </div>
    <button class="toggle-btn" onclick="toggleHoods()">Show all neighbourhoods</button>
</div>

<!-- Undervalued -->
<h2 id="underTitle">Top 15 Undervalued</h2>
<div class="card">
    <div class="table-wrap">
        <table><thead>
            <tr><th>Address</th><th>Neighbourhood</th><th>Asking</th>
                <th>Predicted</th><th>Diff%</th><th>Area</th><th>Energy</th></tr>
        </thead><tbody id="underBody"></tbody></table>
    </div>
</div>

<!-- Overvalued -->
<h2 id="overTitle">Top 15 Overvalued</h2>
<div class="card">
    <div class="table-wrap">
        <table><thead>
            <tr><th>Address</th><th>Neighbourhood</th><th>Asking</th>
                <th>Predicted</th><th>Diff%</th><th>Area</th><th>Energy</th></tr>
        </thead><tbody id="overBody"></tbody></table>
    </div>
</div>

<!-- ── Non-toggled sections ── -->

<!-- Hyperparameters -->
<h2>Hyperparameters</h2>
<div class="card">
    <div class="table-wrap">
        <table>
            <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
            <tbody>{hp_rows}</tbody>
        </table>
    </div>
</div>

<!-- Erfpacht Analysis -->
<h2>Erfpacht Analysis</h2>
<p style="color:#5a5650;font-size:13px;margin-bottom:12px">
    Parsed from {erfpacht['n_parsed']} listings with erfpacht data.
    {erfpacht['expiring_soon']} listings have erfpacht expiring within 10 years.
</p>
<div class="erfpacht-grid">
    <div class="chart-box">
        <h3>Status Distribution</h3>
        <canvas id="erfpachtPie" height="280"></canvas>
    </div>
    <div class="card" style="max-height:400px;overflow-y:auto">
        <h3>Active Erfpacht \u2014 Canon &amp; Expiry</h3>
        <div class="table-wrap">
            <table><thead>
                <tr><th>Address</th><th>Hood</th><th>Canon</th>
                    <th>Expiry</th><th>Yrs Left</th><th>System</th></tr>
            </thead><tbody>{erfpacht['rows_html']}</tbody></table>
        </div>
    </div>
</div>

<!-- Features -->
<h2>Model Features ({n_features} total)</h2>
<div class="card">
    {feature_html}
</div>

<!-- Model History -->
<h2>Model History</h2>
<div class="card" id="historySection">
    <div class="chart-box" style="border:none;padding:0">
        <canvas id="historyChart" height="200"></canvas>
    </div>
    <div id="historyDetail" style="margin-top:12px"></div>
</div>

<p style="color:#5a5650;font-size:11px;margin-top:32px;text-align:center">
    Ground Control &middot; Model Dashboard &middot; {generated_at}
</p>

<script>
// ── Data ──
const D = {dashboard_json};
const charts = {{}};
let currentView = 'both';
let showingAllHoods = false;

Chart.defaults.color = '#5a5650';
Chart.defaults.borderColor = '#1a1c24';
Chart.defaults.font.size = 11;

// ── Helpers ──
function destroyChart(key) {{
    if (charts[key]) {{ charts[key].destroy(); delete charts[key]; }}
}}
function destroyAll() {{
    Object.keys(charts).forEach(k => {{ charts[k].destroy(); delete charts[k]; }});
}}
function fmtEuro(v) {{ return '\u20ac' + Math.round(v).toLocaleString(); }}
function fmtPct(v) {{ return v.toFixed(1) + '%'; }}

// ── Summary Cards ──
function renderSummary(view) {{
    const el = document.getElementById('summaryCards');
    const apt = D.models.apt;
    const house = D.models.house;

    function cardHtml(label, m, n, trained, color) {{
        const am = m.accuracy_bands || {{}};
        const ep = m.error_percentiles || {{}};
        return `
        <div class="card">
            <h3 style="color:${{color}}">${{label}}</h3>
            <div class="metric"><span class="metric-label">CV R\u00b2</span>
                <span class="metric-value big">${{(m.r2||0).toFixed(3)}}</span></div>
            <div class="metric"><span class="metric-label">MAE</span>
                <span class="metric-value">${{fmtEuro(m.mae||0)}}</span></div>
            <div class="metric"><span class="metric-label">RMSE</span>
                <span class="metric-value">${{fmtEuro(m.rmse||0)}}</span></div>
            <div class="metric"><span class="metric-label">MdAPE</span>
                <span class="metric-value">${{fmtPct(m.mdape||0)}}</span></div>
            <div class="metric"><span class="metric-label">MAPE</span>
                <span class="metric-value">${{fmtPct(m.mape||0)}}</span></div>
            <div class="metric"><span class="metric-label">Median Error (P50)</span>
                <span class="metric-value">${{fmtPct(ep.p50||0)}}</span></div>
            <div class="metric"><span class="metric-label">P90 Error</span>
                <span class="metric-value">${{fmtPct(ep.p90||0)}}</span></div>
            <div class="metric"><span class="metric-label">Samples</span>
                <span class="metric-value">${{n}}</span></div>
            <div class="metric"><span class="metric-label">Trained</span>
                <span class="metric-value" style="font-size:12px">${{trained}}</span></div>
        </div>`;
    }}

    if (view === 'both') {{
        el.innerHTML = cardHtml('Apartment Model', apt.metrics, apt.n_samples, apt.trained_at, '#6aad7a')
                     + cardHtml('House Model', house.metrics, house.n_samples, house.trained_at, '#c49a6c');
    }} else if (view === 'apt') {{
        el.innerHTML = cardHtml('Apartment Model', apt.metrics, apt.n_samples, apt.trained_at, '#6aad7a');
    }} else {{
        el.innerHTML = cardHtml('House Model', house.metrics, house.n_samples, house.trained_at, '#c49a6c');
    }}
}}

// ── Accuracy Bands ──
function renderAccuracy(view) {{
    const el = document.getElementById('accuracySection');
    function bandHtml(label, bands, color) {{
        if (!bands) return '';
        let html = `<div class="card"><h3 style="color:${{color}}">${{label}}</h3>`;
        for (const t of ['5','10','15','20']) {{
            const v = bands[t] || 0;
            html += `<div class="acc-bar-wrap">
                <div class="acc-bar-label"><span>Within ${{t}}%</span><span>${{v.toFixed(1)}}%</span></div>
                <div class="acc-bar"><div class="acc-bar-fill" style="width:${{v}}%;background:${{color}}"></div></div>
            </div>`;
        }}
        return html + '</div>';
    }}
    const apt = D.models.apt.metrics;
    const house = D.models.house.metrics;
    if (view === 'both') {{
        el.innerHTML = bandHtml('Apartments', apt.accuracy_bands, '#6aad7a')
                     + bandHtml('Houses', house.accuracy_bands, '#c49a6c');
    }} else if (view === 'apt') {{
        el.innerHTML = bandHtml('Apartments', apt.accuracy_bands, '#6aad7a');
    }} else {{
        el.innerHTML = bandHtml('Houses', house.accuracy_bands, '#c49a6c');
    }}
}}

// ── Scatter Plot ──
function renderScatter(view) {{
    destroyChart('scatter');
    const sd = D.scatter[view];
    const datasets = [];
    if (sd.apt.length) {{
        datasets.push({{
            label: 'Apartments',
            data: sd.apt,
            backgroundColor: view === 'both' ? 'rgba(106,173,122,0.6)' : sd.apt.map(d => d.color),
            pointRadius: view === 'both' ? 2.5 : 3,
            pointHoverRadius: 6,
        }});
    }}
    if (sd.house.length) {{
        datasets.push({{
            label: 'Houses',
            data: sd.house,
            backgroundColor: view === 'both' ? 'rgba(196,154,108,0.6)' : sd.house.map(d => d.color),
            pointRadius: view === 'both' ? 3 : 3,
            pointHoverRadius: 6,
        }});
    }}
    const allPts = [...sd.apt, ...sd.house];
    const maxVal = Math.max(...allPts.map(d => Math.max(d.x, d.y)), 500000);
    const ceil = Math.ceil(maxVal / 500000) * 500000;
    datasets.push({{
        data: [{{x:0,y:0}}, {{x:ceil,y:ceil}}],
        type: 'line', borderColor: '#5a5650', borderDash: [5,5],
        borderWidth: 1, pointRadius: 0, label: 'Perfect',
    }});

    charts.scatter = new Chart(document.getElementById('scatterChart'), {{
        type: 'scatter',
        data: {{ datasets }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: view === 'both', labels: {{ font: {{ size: 11 }} }} }},
                tooltip: {{ callbacks: {{ label: ctx => {{
                    const d = ctx.raw;
                    if (!d.addr) return '';
                    return [d.addr, `Actual: ${{fmtEuro(d.y)}}`, `Predicted: ${{fmtEuro(d.x)}}`, `Error: ${{d.err}}%`];
                }} }} }}
            }},
            scales: {{
                x: {{ title: {{ display: true, text: 'Predicted (\u20ac)' }},
                      ticks: {{ callback: v => '\u20ac' + (v/1000).toFixed(0) + 'k' }} }},
                y: {{ title: {{ display: true, text: 'Actual (\u20ac)' }},
                      ticks: {{ callback: v => '\u20ac' + (v/1000).toFixed(0) + 'k' }} }}
            }}
        }}
    }});
}}

// ── Feature Importance ──
function renderFeatImp(view) {{
    destroyChart('featImpApt'); destroyChart('featImpHouse');
    const el = document.getElementById('featImpSection');

    function makeChart(canvasId, data, color, label) {{
        return new Chart(document.getElementById(canvasId), {{
            type: 'bar',
            data: {{
                labels: data.labels,
                datasets: [{{ data: data.values, backgroundColor: color, borderWidth: 0, label }}]
            }},
            options: {{
                indexAxis: 'y', responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ title: {{ display: true, text: 'Importance' }},
                          ticks: {{ callback: v => (v*100).toFixed(0) + '%' }} }},
                    y: {{ ticks: {{ font: {{ size: 10 }} }} }}
                }}
            }}
        }});
    }}

    if (view === 'both' || view === 'apt') {{
        const showHouse = view === 'both';
        el.innerHTML = `<div class="chart-box"><h3 style="color:#6aad7a">Apartments</h3><canvas id="featImpAptC" height="300"></canvas></div>`
            + (showHouse ? `<div class="chart-box"><h3 style="color:#c49a6c">Houses</h3><canvas id="featImpHouseC" height="300"></canvas></div>` : '');
        charts.featImpApt = makeChart('featImpAptC', D.feat_imp.apt, '#6aad7a', 'Apt');
        if (showHouse) charts.featImpHouse = makeChart('featImpHouseC', D.feat_imp.house, '#c49a6c', 'House');
    }} else {{
        el.innerHTML = `<div class="chart-box"><h3 style="color:#c49a6c">Houses</h3><canvas id="featImpHouseC" height="300"></canvas></div>`;
        charts.featImpHouse = makeChart('featImpHouseC', D.feat_imp.house, '#c49a6c', 'House');
    }}
}}

// ── Per-Fold Stability ──
function renderFolds(view) {{
    destroyChart('foldApt'); destroyChart('foldHouse');
    const el = document.getElementById('foldSection');

    function makeFoldChart(canvasId, folds, color, label) {{
        if (!folds || !folds.length) return null;
        const labels = folds.map(f => 'Fold ' + f.fold);
        return new Chart(document.getElementById(canvasId), {{
            type: 'bar',
            data: {{
                labels,
                datasets: [{{ label: 'R\u00b2', data: folds.map(f => f.r2),
                    backgroundColor: color, borderWidth: 0 }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    y: {{ min: Math.min(...folds.map(f => f.r2)) - 0.02,
                          max: Math.max(...folds.map(f => f.r2)) + 0.01,
                          title: {{ display: true, text: 'R\u00b2' }} }}
                }}
            }}
        }});
    }}

    const aptFolds = D.models.apt.metrics.fold_metrics;
    const houseFolds = D.models.house.metrics.fold_metrics;

    if (view === 'both') {{
        el.innerHTML = `<div class="chart-box"><h3 style="color:#6aad7a">Apartments</h3><canvas id="foldAptC" height="200"></canvas></div>`
            + `<div class="chart-box"><h3 style="color:#c49a6c">Houses</h3><canvas id="foldHouseC" height="200"></canvas></div>`;
        charts.foldApt = makeFoldChart('foldAptC', aptFolds, '#6aad7a', 'Apt');
        charts.foldHouse = makeFoldChart('foldHouseC', houseFolds, '#c49a6c', 'House');
    }} else if (view === 'apt') {{
        el.innerHTML = `<div class="chart-box"><h3 style="color:#6aad7a">Apartments</h3><canvas id="foldAptC" height="200"></canvas></div>`;
        charts.foldApt = makeFoldChart('foldAptC', aptFolds, '#6aad7a', 'Apt');
    }} else {{
        el.innerHTML = `<div class="chart-box"><h3 style="color:#c49a6c">Houses</h3><canvas id="foldHouseC" height="200"></canvas></div>`;
        charts.foldHouse = makeFoldChart('foldHouseC', houseFolds, '#c49a6c', 'House');
    }}
}}

// ── Error by Price Band ──
function renderPriceBand(view) {{
    destroyChart('priceBand');
    const aptBands = D.models.apt.metrics.error_by_price_band || [];
    const houseBands = D.models.house.metrics.error_by_price_band || [];

    let labels, datasets;
    if (view === 'both') {{
        const allBands = new Set([...aptBands.map(b=>b.band), ...houseBands.map(b=>b.band)]);
        labels = Array.from(allBands);
        const aptMap = Object.fromEntries(aptBands.map(b => [b.band, b]));
        const houseMap = Object.fromEntries(houseBands.map(b => [b.band, b]));
        datasets = [
            {{ label: 'Apt Median', data: labels.map(l => (aptMap[l]||{{}}).median_error||0),
               backgroundColor: '#6aad7a', borderWidth: 0 }},
            {{ label: 'Apt P90', data: labels.map(l => (aptMap[l]||{{}}).p90_error||0),
               backgroundColor: 'rgba(106,173,122,0.3)', borderWidth: 1, borderColor: '#6aad7a' }},
            {{ label: 'House Median', data: labels.map(l => (houseMap[l]||{{}}).median_error||0),
               backgroundColor: '#c49a6c', borderWidth: 0 }},
            {{ label: 'House P90', data: labels.map(l => (houseMap[l]||{{}}).p90_error||0),
               backgroundColor: 'rgba(196,154,108,0.3)', borderWidth: 1, borderColor: '#c49a6c' }},
        ];
    }} else {{
        const bands = view === 'apt' ? aptBands : houseBands;
        const color = view === 'apt' ? '#6aad7a' : '#c49a6c';
        labels = bands.map(b => b.band);
        datasets = [
            {{ label: 'Median Error %', data: bands.map(b => b.median_error),
               backgroundColor: color, borderWidth: 0 }},
            {{ label: 'P90 Error %', data: bands.map(b => b.p90_error),
               backgroundColor: color + '40', borderWidth: 1, borderColor: color }},
        ];
    }}

    charts.priceBand = new Chart(document.getElementById('priceBandChart'), {{
        type: 'bar',
        data: {{ labels, datasets }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: true, labels: {{ font: {{ size: 11 }} }} }} }},
            scales: {{ y: {{ title: {{ display: true, text: 'Absolute % Error' }} }} }}
        }}
    }});
}}

// ── Residual Histogram ──
function renderHistogram(view) {{
    destroyChart('hist');
    const labels = D.hist.labels;
    const counts = D.hist[view];
    const colors = labels.map(l => {{
        const d = Math.abs(parseInt(l));
        if (d < 5) return '#6aad7a';
        if (d < 15) return '#c49a6c';
        if (d < 30) return '#d4873e';
        return '#c45050';
    }});
    charts.hist = new Chart(document.getElementById('histResidual'), {{
        type: 'bar',
        data: {{
            labels: labels.map(l => l + '%'),
            datasets: [{{ data: counts, backgroundColor: colors, borderWidth: 0 }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ title: {{ display: true, text: 'Residual % (actual \u2212 predicted) / predicted' }} }},
                y: {{ title: {{ display: true, text: 'Count' }} }}
            }}
        }}
    }});
}}

// ── Residual vs Predicted ──
function renderResidualScatter(view) {{
    destroyChart('residualScatter');
    const datasets = [];
    if (view !== 'house') {{
        const rv = D.models.apt.metrics.residual_vs_predicted;
        if (rv) {{
            datasets.push({{
                label: 'Apartments', data: rv.predicted.map((p,i) => ({{ x: p, y: rv.residual_pct[i] }})),
                backgroundColor: 'rgba(106,173,122,0.4)', pointRadius: 2,
            }});
        }}
    }}
    if (view !== 'apt') {{
        const rv = D.models.house.metrics.residual_vs_predicted;
        if (rv) {{
            datasets.push({{
                label: 'Houses', data: rv.predicted.map((p,i) => ({{ x: p, y: rv.residual_pct[i] }})),
                backgroundColor: 'rgba(196,154,108,0.4)', pointRadius: 2,
            }});
        }}
    }}
    // Zero line
    if (datasets.length) {{
        const allX = datasets.flatMap(ds => ds.data.map(d => d.x));
        const maxX = Math.max(...allX);
        datasets.push({{
            data: [{{x:0,y:0}}, {{x:maxX,y:0}}], type: 'line',
            borderColor: '#5a5650', borderDash: [5,5], borderWidth: 1,
            pointRadius: 0, label: 'Zero',
        }});
    }}
    charts.residualScatter = new Chart(document.getElementById('residualScatter'), {{
        type: 'scatter',
        data: {{ datasets }},
        options: {{
            responsive: true,
            plugins: {{
                legend: {{ display: view === 'both' }},
                tooltip: {{ callbacks: {{ label: ctx => {{
                    const d = ctx.raw;
                    return [`Predicted: ${{fmtEuro(d.x)}}`, `Residual: ${{d.y.toFixed(1)}}%`];
                }} }} }}
            }},
            scales: {{
                x: {{ title: {{ display: true, text: 'Predicted Price (\u20ac)' }},
                      ticks: {{ callback: v => '\u20ac' + (v/1000).toFixed(0) + 'k' }} }},
                y: {{ title: {{ display: true, text: 'Residual %' }} }}
            }}
        }}
    }});
}}

// ── Neighbourhood Table ──
function renderHoods(view) {{
    const data = D.hoods[view];
    const tbody = document.getElementById('hoodBody');
    tbody.innerHTML = data.map(h => `<tr>
        <td>${{h.neighbourhood}}</td>
        <td class="num">${{h.count}}</td>
        <td class="num">${{h.median_abs_error.toFixed(1)}}%</td>
        <td class="num ${{h.mean_residual < 0 ? 'green' : 'red'}}">${{h.mean_residual > 0 ? '+' : ''}}${{h.mean_residual.toFixed(1)}}%</td>
    </tr>`).join('');
    showingAllHoods = false;
    applyHoodFilter();
}}

function applyHoodFilter() {{
    const rows = Array.from(document.getElementById('hoodBody').querySelectorAll('tr'));
    rows.forEach((row, i) => {{ row.style.display = (showingAllHoods || i < 30) ? '' : 'none'; }});
}}

function toggleHoods() {{
    showingAllHoods = !showingAllHoods;
    applyHoodFilter();
    event.target.textContent = showingAllHoods ? 'Show top 30 only' : 'Show all neighbourhoods';
}}

// ── Valued Tables ──
function renderValued(view) {{
    const vd = D.valued[view];
    const viewLabel = view === 'both' ? '' : view === 'apt' ? ' Apartments' : ' Houses';
    document.getElementById('underTitle').textContent = 'Top 15 Undervalued' + viewLabel;
    document.getElementById('overTitle').textContent = 'Top 15 Overvalued' + viewLabel;

    function rowHtml(l, cls) {{
        const area = l.area ? l.area + 'm\u00b2' : '\u2014';
        return `<tr>
            <td><a href="${{l.url}}" target="_blank" rel="noopener">${{l.addr}}</a></td>
            <td>${{l.hood}}</td>
            <td class="num">\u20ac${{l.price.toLocaleString()}}</td>
            <td class="num">\u20ac${{l.pred.toLocaleString()}}</td>
            <td class="num ${{cls}}">${{l.diff > 0 ? '+' : ''}}${{l.diff.toFixed(1)}}%</td>
            <td class="num">${{area}}</td>
            <td>${{l.energy}}</td>
        </tr>`;
    }}

    document.getElementById('underBody').innerHTML = vd.undervalued.map(l => rowHtml(l, 'green')).join('');
    document.getElementById('overBody').innerHTML = vd.overvalued.map(l => rowHtml(l, 'red')).join('');
}}

// ── Sortable Table ──
function sortTable(tableId, colIdx) {{
    const table = document.getElementById(tableId);
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const header = table.querySelectorAll('th')[colIdx];
    const asc = header.dataset.sort !== 'asc';
    table.querySelectorAll('th').forEach(h => delete h.dataset.sort);
    header.dataset.sort = asc ? 'asc' : 'desc';
    rows.sort((a, b) => {{
        let av = a.cells[colIdx].textContent.replace(/[\u20ac%,+]/g, '').trim();
        let bv = b.cells[colIdx].textContent.replace(/[\u20ac%,+]/g, '').trim();
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(r => tbody.appendChild(r));
    showingAllHoods = true;
    applyHoodFilter();
}}

// ── Main View Switcher ──
function switchView(view) {{
    currentView = view;
    document.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.seg-btn').forEach(b => {{
        if (b.textContent.toLowerCase().includes(view === 'both' ? 'both' : view === 'apt' ? 'apartment' : 'house'))
            b.classList.add('active');
    }});

    renderSummary(view);
    renderAccuracy(view);
    renderScatter(view);
    renderFeatImp(view);
    renderFolds(view);
    renderPriceBand(view);
    renderHistogram(view);
    renderResidualScatter(view);
    renderHoods(view);
    renderValued(view);
}}

// ── Erfpacht Pie (static) ──
function renderErfpacht() {{
    const erfStatus = {erfpacht['status_json']};
    const pieLabels = {{
        'eeuwigdurend_afgekocht': 'Eeuwigdurend afgekocht',
        'afgekocht': 'Afgekocht (tijdelijk)',
        'active': 'Active (paying canon)',
        'eigen_grond': 'Eigen grond',
        'unknown': 'Unknown / other'
    }};
    const pieColors = {{
        'eeuwigdurend_afgekocht': '#6aad7a', 'afgekocht': '#c49a6c',
        'active': '#c45050', 'eigen_grond': '#4a8ab5', 'unknown': '#5a5650'
    }};
    const keys = Object.keys(erfStatus);
    new Chart(document.getElementById('erfpachtPie'), {{
        type: 'doughnut',
        data: {{
            labels: keys.map(k => pieLabels[k] || k),
            datasets: [{{
                data: keys.map(k => erfStatus[k]),
                backgroundColor: keys.map(k => pieColors[k] || '#5a5650'),
                borderWidth: 0,
            }}]
        }},
        options: {{
            responsive: true,
            plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }}, padding: 8 }} }} }}
        }}
    }});
}}

// ── Model History Chart ──
function renderHistory() {{
    const hist = D.history;
    if (!hist.length) {{
        document.getElementById('historySection').innerHTML = '<p style="color:#5a5650;font-size:13px">No history yet. Run train_model.py to start tracking.</p>';
        return;
    }}
    const labels = hist.map(h => h.date);
    charts.history = new Chart(document.getElementById('historyChart'), {{
        type: 'line',
        data: {{
            labels,
            datasets: [
                {{ label: 'Apt R\u00b2', data: hist.map(h => h.apt.r2), borderColor: '#6aad7a',
                   backgroundColor: 'rgba(106,173,122,0.1)', fill: true, tension: 0.3 }},
                {{ label: 'House R\u00b2', data: hist.map(h => h.house.r2), borderColor: '#c49a6c',
                   backgroundColor: 'rgba(196,154,108,0.1)', fill: true, tension: 0.3 }},
            ]
        }},
        options: {{
            responsive: true,
            interaction: {{ mode: 'index', intersect: false }},
            plugins: {{
                legend: {{ display: true }},
                tooltip: {{
                    callbacks: {{
                        afterBody: function(ctx) {{
                            const i = ctx[0].dataIndex;
                            const h = hist[i];
                            return [
                                '',
                                `Apt: MAE ${{fmtEuro(h.apt.mae)}} | MdAPE ${{fmtPct(h.apt.mdape)}} | n=${{h.apt.n}}`,
                                `House: MAE ${{fmtEuro(h.house.mae)}} | MdAPE ${{fmtPct(h.house.mdape)}} | n=${{h.house.n}}`,
                                h.apt.accuracy_bands ? `Apt within 10%: ${{h.apt.accuracy_bands['10']}}%` : '',
                                `Features: apt=${{h.apt.n_features}}, house=${{h.house.n_features}}`,
                            ].filter(Boolean);
                        }}
                    }}
                }}
            }},
            scales: {{
                y: {{ title: {{ display: true, text: 'R\u00b2' }},
                      min: Math.min(...hist.map(h => Math.min(h.apt.r2, h.house.r2))) - 0.02 }}
            }},
            onClick: (e, elements) => {{
                if (elements.length) {{
                    const i = elements[0].index;
                    showHistoryDetail(hist[i]);
                }}
            }}
        }}
    }});

    // Show latest entry detail
    showHistoryDetail(hist[hist.length - 1]);
}}

function showHistoryDetail(entry) {{
    const el = document.getElementById('historyDetail');
    const hp = entry.hyperparams || {{}};
    const hpStr = Object.entries(hp).map(([k,v]) => `${{k}}=${{v}}`).join(', ');
    el.innerHTML = `
        <div style="font-size:12px;color:#5a5650">
            <strong style="color:#c49a6c">Run: ${{entry.date}}</strong><br>
            Hyperparams: ${{hpStr}}<br>
            Apt: R\u00b2=${{entry.apt.r2.toFixed(3)}} | MAE=${{fmtEuro(entry.apt.mae)}} | MdAPE=${{fmtPct(entry.apt.mdape)}} | n=${{entry.apt.n}}${{entry.apt.n_features ? ' | features='+entry.apt.n_features : ''}}<br>
            House: R\u00b2=${{entry.house.r2.toFixed(3)}} | MAE=${{fmtEuro(entry.house.mae)}} | MdAPE=${{fmtPct(entry.house.mdape)}} | n=${{entry.house.n}}${{entry.house.n_features ? ' | features='+entry.house.n_features : ''}}
            ${{entry.apt.accuracy_bands ? '<br>Apt accuracy: within 5%=' + entry.apt.accuracy_bands['5'] + '% | 10%=' + entry.apt.accuracy_bands['10'] + '% | 20%=' + entry.apt.accuracy_bands['20'] + '%' : ''}}
            ${{entry.house.accuracy_bands ? '<br>House accuracy: within 5%=' + entry.house.accuracy_bands['5'] + '% | 10%=' + entry.house.accuracy_bands['10'] + '% | 20%=' + entry.house.accuracy_bands['20'] + '%' : ''}}
        </div>`;
}}

// ── Init ──
switchView('both');
renderErfpacht();
renderHistory();
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print('Loading model data...')
    apt_data, house_data = load_pkl_data()

    print('Loading listings with predictions...')
    listings = load_listings_with_predictions()
    print(f'  {len(listings)} listings with predictions')

    print('Parsing erfpacht data...')
    erfpacht_parsed, erfpacht_status_counts = parse_all_erfpacht(listings)
    print(f'  {len(erfpacht_parsed)} parsed, status breakdown: {erfpacht_status_counts}')

    print('Loading model history...')
    model_history = load_model_history()
    print(f'  {len(model_history)} historical entries')

    print('Generating HTML...')
    html = build_html(
        apt_data, house_data, listings,
        erfpacht_parsed, erfpacht_status_counts, model_history
    )

    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f'Written: {OUTPUT_PATH}')

    PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT_PATH, PUBLIC_PATH)
    print(f'Copied:  {PUBLIC_PATH}')


if __name__ == '__main__':
    main()
