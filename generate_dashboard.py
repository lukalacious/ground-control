#!/usr/bin/env python3
"""Generate the Ground Control house-hunting dashboard."""

import argparse
import json
import sqlite3
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from scorer import score_listings

DB_PATH = Path(__file__).parent / "funda.db"
OUTPUT_PATH = Path(__file__).parent / "funda_dashboard.html"
COORDS_PATH = Path(__file__).parent / "neighbourhood_coords.json"


def get_price_history(db_path: str) -> dict[int, list[dict]]:
    """Get price history grouped by global_id."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT global_id, old_price, new_price, recorded_at FROM price_history ORDER BY recorded_at DESC"
    ).fetchall()
    conn.close()

    history: dict[int, list[dict]] = {}
    for r in rows:
        gid = r["global_id"]
        if gid not in history:
            history[gid] = []
        history[gid].append({
            "old_price": r["old_price"],
            "new_price": r["new_price"],
            "date": r["recorded_at"][:10] if r["recorded_at"] else None,
        })
    return history


def get_stats(db_path: str) -> dict:
    """Get latest city stats."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM city_stats ORDER BY calculated_at DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"avg_price_m2": 0, "median_price": 0, "median_days_on_market": 0, "listing_count": 0}


def get_neighbourhood_stats(db_path: str) -> dict:
    """Get neighbourhood stats as a dict keyed by name."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM neighbourhood_stats ORDER BY listing_count DESC").fetchall()
    conn.close()
    return {r["neighbourhood"]: {"avg_price_m2": round(r["avg_price_m2"], 1), "median_price": r["median_price"], "count": r["listing_count"]} for r in rows}


def count_new_today(db_path: str) -> int:
    """Count listings first seen in the last 24h."""
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE is_active = 1 AND first_seen >= datetime('now', '-1 day')"
    ).fetchone()[0]
    conn.close()
    return count


def load_coords(coords_path: Path) -> dict:
    """Load neighbourhood coordinates from geocoder cache."""
    if coords_path.exists():
        return json.loads(coords_path.read_text(encoding="utf-8"))
    return {}


def build_map_data(hood_stats: dict, coords: dict) -> dict:
    """Merge neighbourhood stats with coordinates into map data."""
    map_data = {}
    for name, stats in hood_stats.items():
        if name in coords:
            lat, lng = coords[name]
            map_data[name] = {
                "avg_price_m2": stats["avg_price_m2"],
                "median_price": stats["median_price"],
                "count": stats["count"],
                "lat": lat,
                "lng": lng,
            }
    return map_data


def build_html(listings_json: str, stats_json: str, hood_stats_json: str,
               map_data_json: str, generated_at: str) -> str:
    """Build the complete HTML dashboard."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ground Control — Amsterdam</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #08090d;
            color: #c8c4be;
            padding: 20px;
            line-height: 1.4;
        }}
        h1 {{ color: #c49a6c; margin-bottom: 6px; font-size: 24px; letter-spacing: 0.5px; }}
        .subtitle {{ color: #5a5650; font-size: 13px; margin-bottom: 20px; }}

        /* Stats bar */
        .stats-bar {{
            display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;
        }}
        .stat {{
            background: #111318; padding: 12px 18px; border-radius: 10px;
            min-width: 100px; text-align: center; flex: 1;
            border: 1px solid #1a1c24;
        }}
        .stat-value {{ font-size: 20px; font-weight: 700; color: #c49a6c; }}
        .stat-label {{ font-size: 10px; color: #5a5650; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }}

        /* Filters */
        .filters {{
            background: #111318; padding: 14px 16px; border-radius: 10px;
            margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap;
            align-items: flex-end; border: 1px solid #1a1c24;
        }}
        .fg {{ display: flex; flex-direction: column; gap: 4px; }}
        .fg label {{ font-size: 10px; color: #6b6762; text-transform: uppercase; letter-spacing: 0.3px; }}
        .fg input, .fg select {{
            padding: 7px 10px; border: 1px solid #1e2028; border-radius: 6px;
            background: #161a24; color: #c8c4be; font-size: 13px; min-width: 100px;
        }}
        .fg input:focus, .fg select:focus {{ outline: none; border-color: #c49a6c; }}
        .fg .range {{ display: flex; gap: 4px; }}
        .fg .range input {{ min-width: 75px; width: 85px; }}
        .toggles {{ display: flex; gap: 10px; align-items: center; margin-left: 4px; }}
        .toggle {{ display: flex; align-items: center; gap: 5px; cursor: pointer; font-size: 12px; color: #7a7672; }}
        .toggle input {{ accent-color: #c49a6c; }}
        .btn {{
            padding: 8px 16px; background: #c49a6c; color: #0a0b10; border: none;
            border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 13px;
        }}
        .btn:hover {{ background: #a8845a; }}
        .btn-ghost {{
            background: transparent; border: 1px solid #252530; color: #6b6762;
        }}
        .btn-ghost:hover {{ border-color: #c49a6c; color: #c49a6c; }}

        /* Grid */
        .result-bar {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 14px; font-size: 13px; color: #5a5650;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 14px;
        }}
        .card {{
            background: #111318; border-radius: 10px; overflow: hidden;
            transition: transform 0.15s, box-shadow 0.15s; position: relative;
            border: 1px solid #1a1c24;
        }}
        .card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,.5); border-color: #252530; }}
        .card-img {{
            height: 170px; background: #0c0d12; overflow: hidden;
            display: flex; align-items: center; justify-content: center;
        }}
        .card-img img {{ width: 100%; height: 100%; object-fit: cover; }}
        .card-body {{ padding: 14px; }}
        .card-price {{ font-size: 22px; font-weight: 700; color: #c49a6c; }}
        .card-prev-price {{ font-size: 13px; color: #7a3030; text-decoration: line-through; margin-left: 8px; }}
        .card-address {{ font-size: 14px; color: #c8c4be; margin: 4px 0; }}
        .card-pm2 {{ font-size: 12px; color: #5a5650; margin-bottom: 8px; }}
        .card-details {{
            display: grid; grid-template-columns: repeat(3, 1fr);
            gap: 6px; font-size: 12px;
        }}
        .det {{ background: #161a24; padding: 7px; border-radius: 6px; text-align: center; }}
        .det-label {{ font-size: 10px; color: #5a5650; }}
        .det-value {{ font-weight: 600; color: #c49a6c; }}
        .card-meta {{
            margin-top: 10px; padding-top: 10px; border-top: 1px solid #1a1c24;
            font-size: 12px; color: #5a5650; display: flex; justify-content: space-between;
            align-items: center;
        }}
        .card-meta a {{ color: #c49a6c; text-decoration: none; font-weight: 500; }}
        .card-meta a:hover {{ text-decoration: underline; color: #d4b48a; }}

        /* Badges */
        .badges {{ position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; }}
        .badge {{
            padding: 3px 8px; border-radius: 4px; font-size: 11px;
            font-weight: 600; text-transform: uppercase;
        }}
        .badge-new {{ background: #c49a6c; color: #0a0b10; }}
        .badge-drop {{ background: #7a3030; color: #ddd; }}
        .badge-score {{
            position: absolute; top: 10px; right: 10px;
            padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
        }}
        .score-high {{ background: #c49a6c; color: #0a0b10; }}
        .score-mid {{ background: #c49a6c; color: #111; }}
        .score-low {{ background: #1e2028; color: #5a5650; }}

        /* Energy labels */
        .el-A, .el-Ap {{ color: #6aad7a; }} .el-B {{ color: #94a86a; }}
        .el-C {{ color: #c49a6c; }} .el-D {{ color: #c47a50; }}
        .el-E {{ color: #a04040; }} .el-F, .el-G {{ color: #7a3030; }}

        /* Neighbourhood panel */
        .hood-panel {{
            background: #111318; border-radius: 10px; padding: 16px 20px;
            margin-bottom: 20px; display: none; border: 1px solid #1a1c24;
        }}
        .hood-panel.open {{ display: block; }}
        .hood-panel h3 {{ color: #c49a6c; margin-bottom: 12px; font-size: 16px; }}
        .hood-controls {{
            display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;
        }}
        .hood-controls .btn {{ padding: 5px 12px; font-size: 11px; }}
        .hood-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        .hood-table th {{
            text-align: left; padding: 8px 12px; color: #6b6762; border-bottom: 1px solid #1e2028;
            cursor: pointer; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .hood-table th:hover {{ color: #c49a6c; }}
        .hood-table td {{ padding: 8px 12px; border-bottom: 1px solid #141820; }}
        .hood-table tr:hover td {{ background: #161a24; }}
        .hood-table td:first-child {{ width: 30px; text-align: center; }}
        .hood-table input[type="checkbox"] {{ accent-color: #c49a6c; cursor: pointer; }}
        .hood-table tr.excluded td {{ opacity: 0.35; }}

        /* Load more */
        .load-more {{
            text-align: center; padding: 30px;
        }}

        /* View toggle */
        .view-toggle {{
            display: flex; gap: 4px; margin-left: auto;
        }}
        .view-btn {{
            padding: 7px 14px; border: 1px solid #252530; border-radius: 6px;
            background: transparent; color: #6b6762; cursor: pointer;
            font-size: 12px; font-weight: 600;
        }}
        .view-btn.active {{
            background: #c49a6c; color: #0a0b10; border-color: #c49a6c;
        }}
        .view-btn:hover:not(.active) {{ border-color: #c49a6c; color: #c49a6c; }}

        /* Map */
        #mapContainer {{ display: none; }}
        #mapContainer.active {{ display: block; }}
        #map {{ height: 70vh; border-radius: 10px; z-index: 1; }}
        .map-legend {{
            margin-top: 12px; background: #111318; border-radius: 10px;
            padding: 14px 20px; display: flex; align-items: center; gap: 14px;
            font-size: 12px; color: #5a5650; border: 1px solid #1a1c24;
        }}
        .legend-gradient {{
            flex: 1; height: 12px; border-radius: 6px;
            background: linear-gradient(to right, #2a6e4a, #6a8a3a, #c49a6c, #c47a50, #b85a3a, #8b2020);
        }}
        .legend-label {{ white-space: nowrap; }}

        /* Leaflet popup overrides */
        .leaflet-popup-content-wrapper {{
            background: #111318; color: #c8c4be; border-radius: 8px;
            border: 1px solid #252530;
        }}
        .leaflet-popup-tip {{ background: #111318; }}
        .leaflet-popup-content {{ font-size: 13px; line-height: 1.5; }}
        .leaflet-popup-content a {{ color: #c49a6c; }}
        .popup-listing {{ margin: 4px 0; padding: 3px 0; border-bottom: 1px solid #1e2028; }}
        .popup-listing:last-child {{ border-bottom: none; }}
        .bubble-label {{
            background: none !important; border: none !important;
            display: flex; align-items: center; justify-content: center;
        }}
        .bubble-label span {{
            color: #fff; font-size: 11px; font-weight: 700;
            text-shadow: 0 1px 3px rgba(0,0,0,.8);
            pointer-events: none;
        }}

        /* Mobile */
        @media (max-width: 768px) {{
            body {{ padding: 12px; }}
            h1 {{ font-size: 20px; }}
            .stats-bar {{ gap: 6px; }}
            .stat {{ min-width: 0; padding: 10px 8px; flex: 1 1 calc(33% - 6px); }}
            .stat-value {{ font-size: 16px; }}
            .stat-label {{ font-size: 9px; }}
            .filters {{
                padding: 12px; gap: 8px;
                flex-direction: column; align-items: stretch;
            }}
            .fg {{ width: 100%; }}
            .fg input, .fg select {{ width: 100%; min-width: 0; }}
            .fg .range {{ flex: 1; }}
            .fg .range input {{ flex: 1; min-width: 0; width: auto; }}
            .toggles {{ margin-left: 0; justify-content: flex-start; }}
            .filters > .btn, .filters > .btn-ghost {{ width: auto; }}
            .view-toggle {{ margin-left: 0; width: 100%; }}
            .view-btn {{ flex: 1; text-align: center; }}
            .grid {{ grid-template-columns: 1fr; gap: 12px; }}
            .card-img {{ height: 200px; }}
            #map {{ height: 55vh; }}
            .map-legend {{ padding: 10px 14px; gap: 8px; font-size: 11px; flex-wrap: wrap; }}
            .hood-panel {{ padding: 12px; }}
            .hood-controls {{ flex-wrap: wrap; }}
            .hood-table {{ font-size: 12px; }}
            .hood-table th, .hood-table td {{ padding: 6px 8px; }}
        }}

        @media (max-width: 400px) {{
            .stat {{ flex: 1 1 calc(50% - 6px); }}
            .card-img {{ height: 160px; }}
            .card-body {{ padding: 12px; }}
            .card-price {{ font-size: 20px; }}
        }}
    </style>
</head>
<body>
    <h1>Ground Control</h1>
    <div class="subtitle">Generated {generated_at[:16].replace('T', ' ')} UTC — Amsterdam housing intel (All prices)</div>

    <div class="stats-bar" id="statsBar"></div>

    <div class="filters">
        <div class="fg">
            <label>Price</label>
            <div class="range">
                <input type="number" id="fMinPrice" placeholder="Min" step="5000">
                <input type="number" id="fMaxPrice" placeholder="Max" step="5000">
            </div>
        </div>
        <div class="fg">
            <label>Area (m&sup2;)</label>
            <div class="range">
                <input type="number" id="fMinArea" placeholder="Min" step="5">
                <input type="number" id="fMaxArea" placeholder="Max" step="5">
            </div>
        </div>
        <div class="fg">
            <label>Bedrooms</label>
            <input type="number" id="fMinBed" placeholder="Min" min="0" max="10">
        </div>
        <div class="fg">
            <label>Energy</label>
            <select id="fEnergy">
                <option value="">All</option>
                <option value="A">A+</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="D">D</option>
                <option value="E">E+</option>
            </select>
        </div>
        <div class="fg">
            <label>Neighbourhood</label>
            <select id="fHood"><option value="">All</option></select>
        </div>
        <div class="fg">
            <label>Sort by</label>
            <select id="fSort">
                <option value="score">Best deal score</option>
                <option value="price_asc">Price (low to high)</option>
                <option value="price_desc">Price (high to low)</option>
                <option value="pm2_asc">EUR/m&sup2; (lowest)</option>
                <option value="area_desc">Area (largest)</option>
                <option value="beds_desc">Bedrooms (most)</option>
                <option value="newest">Newest first</option>
                <option value="dom_desc">Longest on market</option>
            </select>
        </div>
        <div class="toggles">
            <label class="toggle"><input type="checkbox" id="fNewOnly"> New (24h)</label>
            <label class="toggle"><input type="checkbox" id="fDropOnly"> Price drops</label>
        </div>
        <button class="btn" onclick="applyFilters()">Filter</button>
        <button class="btn btn-ghost" onclick="resetFilters()">Reset</button>
        <button class="btn btn-ghost" id="hoodToggleBtn" onclick="toggleHoods()">Neighbourhoods</button>
        <div class="view-toggle">
            <button class="view-btn active" id="viewGrid" onclick="setView('grid')">Grid</button>
            <button class="view-btn" id="viewMap" onclick="setView('map')">Map</button>
        </div>
    </div>

    <div class="hood-panel" id="hoodPanel">
        <h3>Neighbourhood Comparison</h3>
        <div class="hood-controls">
            <button class="btn btn-ghost" onclick="hoodSelectAll(true)">Select All</button>
            <button class="btn btn-ghost" onclick="hoodSelectAll(false)">Deselect All</button>
            <button class="btn btn-ghost" onclick="hoodInvert()">Invert</button>
            <span id="hoodExcludeCount" style="font-size:12px;color:#888;margin-left:8px;"></span>
        </div>
        <table class="hood-table" id="hoodTable">
            <thead><tr>
                <th style="cursor:default;"></th>
                <th onclick="sortHoodTable(0)">Neighbourhood</th>
                <th onclick="sortHoodTable(1)">Listings</th>
                <th onclick="sortHoodTable(2)">Avg EUR/m&sup2;</th>
                <th onclick="sortHoodTable(3)">Median Price</th>
            </tr></thead>
            <tbody></tbody>
        </table>
    </div>

    <div id="mapContainer">
        <div id="map"></div>
        <div class="map-legend">
            <span class="legend-label">&euro;3,500/m&sup2;</span>
            <div class="legend-gradient"></div>
            <span class="legend-label">&euro;11,500/m&sup2;</span>
            <span style="margin-left:12px; color:#555;">Size = listing count</span>
        </div>
    </div>

    <div id="gridContainer">
    <div class="result-bar">
        <span>Showing <strong id="showCount">0</strong> of <strong id="totalCount">0</strong> properties</span>
    </div>

    <div class="grid" id="grid"></div>
    <div class="load-more" id="loadMore" style="display:none;">
        <button class="btn" onclick="loadMore()">Load more</button>
    </div>
    </div><!-- /gridContainer -->

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const LISTINGS = {listings_json};
const STATS = {stats_json};
const NEIGHBOURHOOD_STATS = {hood_stats_json};
const MAP_DATA = {map_data_json};
const GENERATED_AT = "{generated_at}";
const PAGE_SIZE = 50;

let filtered = [];
let showing = 0;
let currentView = 'grid';
let leafletMap = null;
let mapMarkers = [];
let excludedHoods = new Set(JSON.parse(localStorage.getItem('funda_excluded_hoods') || '[]'));

// ── Init ──
function init() {{
    renderStats();
    populateHoodDropdown();
    renderHoodTable();
    applyFilters();
}}

function renderStats() {{
    const s = STATS;
    const newToday = LISTINGS.filter(l => isNew(l)).length;
    const drops = LISTINGS.filter(l => l.previous_price && l.previous_price > l.price_numeric).length;
    document.getElementById('statsBar').innerHTML = `
        <div class="stat"><div class="stat-value">${{s.listing_count}}</div><div class="stat-label">Active</div></div>
        <div class="stat"><div class="stat-value">${{newToday}}</div><div class="stat-label">New (24h)</div></div>
        <div class="stat"><div class="stat-value">${{drops}}</div><div class="stat-label">Price Drops</div></div>
        <div class="stat"><div class="stat-value">&euro;${{Math.round(s.avg_price_m2).toLocaleString()}}</div><div class="stat-label">Avg EUR/m&sup2;</div></div>
        <div class="stat"><div class="stat-value">&euro;${{Math.round(s.median_price).toLocaleString()}}</div><div class="stat-label">Median Price</div></div>
        <div class="stat"><div class="stat-value">${{Math.round(s.median_days_on_market)}}d</div><div class="stat-label">Median DOM</div></div>
    `;
}}

function isNew(l) {{
    if (!l.first_seen) return false;
    const fs = new Date(l.first_seen);
    const gen = new Date(GENERATED_AT);
    return (gen - fs) < 86400000;
}}

function hasDrop(l) {{
    return l.previous_price && l.previous_price > l.price_numeric;
}}

// ── Filtering ──
function applyFilters() {{
    const minP = parseInt(document.getElementById('fMinPrice').value) || 0;
    const maxP = parseInt(document.getElementById('fMaxPrice').value) || Infinity;
    const minA = parseInt(document.getElementById('fMinArea').value) || 0;
    const maxA = parseInt(document.getElementById('fMaxArea').value) || Infinity;
    const minB = parseInt(document.getElementById('fMinBed').value) || 0;
    const energy = document.getElementById('fEnergy').value;
    const hood = document.getElementById('fHood').value;
    const newOnly = document.getElementById('fNewOnly').checked;
    const dropOnly = document.getElementById('fDropOnly').checked;
    const sort = document.getElementById('fSort').value;

    filtered = LISTINGS.filter(l => {{
        if (l.price_numeric < minP || l.price_numeric > maxP) return false;
        if ((l.living_area || 0) < minA || (l.living_area || 0) > maxA) return false;
        if ((l.bedrooms || 0) < minB) return false;
        if (energy) {{
            const el = (l.energy_label || '').replace('+', '').replace('++', '').replace('+++', '');
            if (energy === 'A' && !['A', 'A+', 'A++', 'A+++', 'A++++'].includes(l.energy_label)) return false;
            if (energy === 'E' && !['E', 'F', 'G'].includes(el)) return false;
            if (energy !== 'A' && energy !== 'E' && el !== energy) return false;
        }}
        if (excludedHoods.has(l.neighbourhood)) return false;
        if (hood && l.neighbourhood !== hood) return false;
        if (newOnly && !isNew(l)) return false;
        if (dropOnly && !hasDrop(l)) return false;
        return true;
    }});

    // Sort
    const sorters = {{
        score: (a, b) => (b.score || 0) - (a.score || 0),
        price_asc: (a, b) => a.price_numeric - b.price_numeric,
        price_desc: (a, b) => b.price_numeric - a.price_numeric,
        pm2_asc: (a, b) => (a.price_m2 || 99999) - (b.price_m2 || 99999),
        area_desc: (a, b) => (b.living_area || 0) - (a.living_area || 0),
        beds_desc: (a, b) => (b.bedrooms || 0) - (a.bedrooms || 0),
        newest: (a, b) => (b.first_seen || '').localeCompare(a.first_seen || ''),
        dom_desc: (a, b) => {{
            const da = a.score_details?.days_on_market || 0;
            const db_ = b.score_details?.days_on_market || 0;
            return db_ - da;
        }},
    }};
    filtered.sort(sorters[sort] || sorters.score);

    showing = 0;
    document.getElementById('grid').innerHTML = '';
    document.getElementById('showCount').textContent = '0';
    document.getElementById('totalCount').textContent = filtered.length;
    loadMore();
    if (currentView === 'map') updateMap();
}}

function resetFilters() {{
    document.getElementById('fMinPrice').value = '';
    document.getElementById('fMaxPrice').value = '';
    document.getElementById('fMinArea').value = '';
    document.getElementById('fMaxArea').value = '';
    document.getElementById('fMinBed').value = '';
    document.getElementById('fEnergy').value = '';
    document.getElementById('fHood').value = '';
    document.getElementById('fSort').value = 'score';
    document.getElementById('fNewOnly').checked = false;
    document.getElementById('fDropOnly').checked = false;
    applyFilters();
}}

// ── Rendering ──
function loadMore() {{
    const grid = document.getElementById('grid');
    const end = Math.min(showing + PAGE_SIZE, filtered.length);

    for (let i = showing; i < end; i++) {{
        grid.appendChild(createCard(filtered[i]));
    }}
    showing = end;
    document.getElementById('showCount').textContent = showing;
    document.getElementById('loadMore').style.display = showing < filtered.length ? 'block' : 'none';
}}

function createCard(l) {{
    const div = document.createElement('div');
    div.className = 'card';

    const isN = isNew(l);
    const drop = hasDrop(l);
    const dropPct = drop ? Math.round((1 - l.price_numeric / l.previous_price) * 100) : 0;

    // Score badge class
    let sc = 'score-low';
    if (l.score >= 15) sc = 'score-high';
    else if (l.score >= 5) sc = 'score-mid';

    // Energy label class
    const elBase = (l.energy_label || '').replace(/[+]/g, '');
    const elClass = 'el-' + (elBase || 'X');

    const pm2 = l.price_m2 ? `&euro;${{Math.round(l.price_m2).toLocaleString()}}/m&sup2;` : '';
    const prevHtml = drop ? `<span class="card-prev-price">&euro;${{l.previous_price.toLocaleString()}}</span>` : '';

    div.innerHTML = `
        <div class="badges">
            ${{isN ? '<span class="badge badge-new">New</span>' : ''}}
            ${{drop ? `<span class="badge badge-drop">-${{dropPct}}%</span>` : ''}}
        </div>
        <span class="badge-score ${{sc}}" title="Score: ${{l.score}}&#10;vs neighbourhood: ${{l.score_details?.vs_neighbourhood_pct ?? 'n/a'}}%&#10;vs city: ${{l.score_details?.vs_city_pct ?? 'n/a'}}%&#10;Days on market: ${{l.score_details?.days_on_market ?? '?'}}">${{l.score?.toFixed(1) || '—'}}</span>
        <div class="card-img">${{l.image_url ? `<img src="${{l.image_url}}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}}</div>
        <div class="card-body">
            <div class="card-price">&euro;${{l.price_numeric.toLocaleString()}}${{prevHtml}}</div>
            <div class="card-address">${{l.address || 'Unknown'}}</div>
            <div class="card-pm2">${{pm2}}</div>
            <div class="card-details">
                <div class="det"><div class="det-label">m&sup2;</div><div class="det-value">${{l.living_area || '—'}}</div></div>
                <div class="det"><div class="det-label">Beds</div><div class="det-value">${{l.bedrooms ?? '—'}}</div></div>
                <div class="det"><div class="det-label">Energy</div><div class="det-value ${{elClass}}">${{l.energy_label || '—'}}</div></div>
            </div>
            <div class="card-meta">
                <span>${{l.neighbourhood || l.city || ''}}</span>
                <a href="${{l.detail_url}}" target="_blank" rel="noopener">View listing &rarr;</a>
            </div>
        </div>
    `;
    return div;
}}

// ── Neighbourhood panel ──
function populateHoodDropdown() {{
    const sel = document.getElementById('fHood');
    const prev = sel.value;
    // Keep first "All" option, clear the rest
    while (sel.options.length > 1) sel.remove(1);
    const hoods = [...new Set(LISTINGS.map(l => l.neighbourhood).filter(Boolean))]
        .filter(h => !excludedHoods.has(h)).sort();
    hoods.forEach(h => {{
        const opt = document.createElement('option');
        opt.value = h; opt.textContent = h;
        sel.appendChild(opt);
    }});
    // Restore previous selection if still valid
    if (hoods.includes(prev)) sel.value = prev;
    else sel.value = '';
}}

function toggleHoods() {{
    document.getElementById('hoodPanel').classList.toggle('open');
}}

let hoodSortCol = -1;
let hoodSortAsc = true;

function renderHoodTable() {{
    const tbody = document.querySelector('#hoodTable tbody');
    let rows = Object.entries(NEIGHBOURHOOD_STATS).map(([name, s]) => ({{
        name, count: s.count, avg_m2: s.avg_price_m2, median: s.median_price
    }}));

    if (hoodSortCol >= 0) {{
        const keys = ['name', 'count', 'avg_m2', 'median'];
        const key = keys[hoodSortCol];
        rows.sort((a, b) => {{
            if (typeof a[key] === 'string') return hoodSortAsc ? a[key].localeCompare(b[key]) : b[key].localeCompare(a[key]);
            return hoodSortAsc ? a[key] - b[key] : b[key] - a[key];
        }});
    }}

    tbody.innerHTML = rows.map(r => {{
        const checked = !excludedHoods.has(r.name);
        const cls = checked ? '' : ' class="excluded"';
        return `<tr${{cls}}>
            <td><input type="checkbox" data-hood="${{r.name}}" ${{checked ? 'checked' : ''}} onchange="onHoodToggle(this)"></td>
            <td>${{r.name}}</td>
            <td>${{r.count}}</td>
            <td>&euro;${{Math.round(r.avg_m2).toLocaleString()}}</td>
            <td>&euro;${{Math.round(r.median).toLocaleString()}}</td>
        </tr>`;
    }}).join('');
    updateHoodExcludeCount();
}}

function sortHoodTable(col) {{
    if (hoodSortCol === col) hoodSortAsc = !hoodSortAsc;
    else {{ hoodSortCol = col; hoodSortAsc = col === 0; }}
    renderHoodTable();
}}

function onHoodToggle(cb) {{
    const hood = cb.dataset.hood;
    if (cb.checked) excludedHoods.delete(hood);
    else excludedHoods.add(hood);
    cb.closest('tr').classList.toggle('excluded', !cb.checked);
    saveExcludedHoods();
    populateHoodDropdown();
    applyFilters();
}}

function hoodSelectAll(include) {{
    excludedHoods = include ? new Set() : new Set(Object.keys(NEIGHBOURHOOD_STATS));
    saveExcludedHoods();
    renderHoodTable();
    populateHoodDropdown();
    applyFilters();
}}

function hoodInvert() {{
    const all = Object.keys(NEIGHBOURHOOD_STATS);
    const newExcluded = new Set(all.filter(h => !excludedHoods.has(h)));
    excludedHoods = newExcluded;
    saveExcludedHoods();
    renderHoodTable();
    populateHoodDropdown();
    applyFilters();
}}

function saveExcludedHoods() {{
    localStorage.setItem('funda_excluded_hoods', JSON.stringify([...excludedHoods]));
    updateHoodExcludeCount();
}}

function updateHoodExcludeCount() {{
    const n = excludedHoods.size;
    const countEl = document.getElementById('hoodExcludeCount');
    const btn = document.getElementById('hoodToggleBtn');
    countEl.textContent = n > 0 ? `${{n}} hidden` : '';
    btn.textContent = n > 0 ? `Neighbourhoods (${{n}} hidden)` : 'Neighbourhoods';
}}

// ── Map ──
function initMap() {{
    if (leafletMap) return;
    leafletMap = L.map('map').setView([52.3676, 4.9041], 12);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }}).addTo(leafletMap);
}}

function priceToColor(priceM2) {{
    // Muted teal (affordable) → Dusty gold → Mars rust (expensive)
    const min = 3500, max = 11500;
    const t = Math.max(0, Math.min(1, (priceM2 - min) / (max - min)));
    let r, g, b;
    if (t < 0.5) {{
        const s = t * 2;
        r = Math.round(42 + s * 154);  // 42 → 196
        g = Math.round(110 + s * 44);  // 110 → 154
        b = Math.round(74 - s * 30);   // 74 → 44 (warm shift)
    }} else {{
        const s = (t - 0.5) * 2;
        r = Math.round(196 + s * 16);  // 196 → 212
        g = Math.round(154 - s * 96);  // 154 → 58
        b = Math.round(44 - s * 12);   // 44 → 32
    }}
    return `rgb(${{r}},${{g}},${{b}})`;
}}

function bubbleRadius(count) {{
    return Math.max(8, Math.min(40, 8 + Math.sqrt(count) * 5.75));
}}

function updateMap() {{
    if (!leafletMap) return;

    // Clear existing markers
    mapMarkers.forEach(m => leafletMap.removeLayer(m));
    mapMarkers = [];

    // Aggregate filtered listings by neighbourhood
    const agg = {{}};
    filtered.forEach(l => {{
        const hood = l.neighbourhood;
        if (!hood || !MAP_DATA[hood]) return;
        if (!agg[hood]) agg[hood] = {{ listings: [], totalPm2: 0, count: 0 }};
        agg[hood].listings.push(l);
        if (l.price_m2) {{ agg[hood].totalPm2 += l.price_m2; agg[hood].count++; }}
    }});

    Object.entries(agg).forEach(([hood, data]) => {{
        const md = MAP_DATA[hood];
        const avgPm2 = data.count > 0 ? data.totalPm2 / data.count : md.avg_price_m2;
        const color = priceToColor(avgPm2);
        const radius = bubbleRadius(data.listings.length);

        const marker = L.circleMarker([md.lat, md.lng], {{
            radius: radius,
            fillColor: color,
            color: '#fff',
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.7,
        }}).addTo(leafletMap);

        // Count label inside bubble
        const label = L.marker([md.lat, md.lng], {{
            icon: L.divIcon({{
                className: 'bubble-label',
                html: `<span>${{data.listings.length}}</span>`,
                iconSize: [radius * 2, radius * 2],
                iconAnchor: [radius, radius],
            }}),
            interactive: false,
        }}).addTo(leafletMap);
        mapMarkers.push(label);

        // Build popup with top 5 listings
        const top5 = data.listings
            .sort((a, b) => (a.price_m2 || 99999) - (b.price_m2 || 99999))
            .slice(0, 5);

        let popupHtml = `<strong>${{hood}}</strong><br>`;
        popupHtml += `<span style="color:#888">${{data.listings.length}} listings &middot; Avg &euro;${{Math.round(avgPm2).toLocaleString()}}/m&sup2;</span>`;

        if (top5.length > 0) {{
            popupHtml += '<div style="margin-top:6px">';
            top5.forEach(l => {{
                popupHtml += `<div class="popup-listing">`;
                popupHtml += `<a href="${{l.detail_url}}" target="_blank">&euro;${{l.price_numeric.toLocaleString()}}</a>`;
                popupHtml += ` &middot; ${{l.living_area || '?'}}m&sup2;`;
                if (l.price_m2) popupHtml += ` &middot; &euro;${{Math.round(l.price_m2).toLocaleString()}}/m&sup2;`;
                popupHtml += `<br><span style="color:#888;font-size:11px">${{l.address || ''}}</span>`;
                popupHtml += `</div>`;
            }});
            popupHtml += '</div>';
        }}

        marker.bindPopup(popupHtml, {{ maxWidth: 300 }});
        mapMarkers.push(marker);
    }});
}}

function setView(view) {{
    currentView = view;
    const gridContainer = document.getElementById('gridContainer');
    const mapContainer = document.getElementById('mapContainer');

    document.getElementById('viewGrid').classList.toggle('active', view === 'grid');
    document.getElementById('viewMap').classList.toggle('active', view === 'map');

    if (view === 'map') {{
        gridContainer.style.display = 'none';
        mapContainer.classList.add('active');
        initMap();
        setTimeout(() => {{
            leafletMap.invalidateSize();
            updateMap();
        }}, 100);
    }} else {{
        mapContainer.classList.remove('active');
        gridContainer.style.display = 'block';
    }}
}}

// ── Auto-filter on Enter / input change ──
document.addEventListener('DOMContentLoaded', () => {{
    document.querySelectorAll('.filters input, .filters select').forEach(el => {{
        el.addEventListener('keydown', e => {{ if (e.key === 'Enter') applyFilters(); }});
        if (el.tagName === 'SELECT' || el.type === 'checkbox') {{
            el.addEventListener('change', applyFilters);
        }}
    }});
    init();
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Ground Control dashboard")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    args = parser.parse_args()

    db = args.db

    # Score all listings
    scored = score_listings(db)

    # Supplementary data
    price_hist = get_price_history(db)
    stats = get_stats(db)
    hood_stats = get_neighbourhood_stats(db)
    stats["new_today"] = count_new_today(db)

    # Load neighbourhood coordinates and build map data
    coords = load_coords(COORDS_PATH)
    map_data = build_map_data(hood_stats, coords)

    # Merge price history into scored listings
    for listing in scored:
        listing["price_history"] = price_hist.get(listing["global_id"], [])

    # Serialize
    generated_at = datetime.now(timezone.utc).isoformat()
    listings_json = json.dumps(scored, default=str)
    stats_json = json.dumps(stats)
    hood_stats_json = json.dumps(hood_stats)
    map_data_json = json.dumps(map_data)

    # Build and write
    html = build_html(listings_json, stats_json, hood_stats_json, map_data_json, generated_at)
    Path(args.output).write_text(html, encoding="utf-8")
    print(f"Dashboard: {args.output} ({len(html):,} bytes, {len(scored)} listings)")

    if args.open:
        webbrowser.open(f"file://{Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
