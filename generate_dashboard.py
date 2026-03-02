#!/usr/bin/env python3
"""Generate the Ground Control house-hunting dashboard."""

import argparse
import json
import sqlite3
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from scorer import score_listings

DB_PATH = Path(__file__).parent / "ground_control.db"
OUTPUT_PATH = Path(__file__).parent / "ground_control_dashboard.html"
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
            entry = coords[name]
            lat, lng = entry[0], entry[1]
            wijk = entry[2] if len(entry) >= 3 else ""
            stadsdeel = entry[3] if len(entry) >= 4 else ""
            map_data[name] = {
                "avg_price_m2": stats["avg_price_m2"],
                "median_price": stats["median_price"],
                "count": stats["count"],
                "lat": lat,
                "lng": lng,
                "wijk": wijk,
                "stadsdeel": stadsdeel,
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
        .subtitle {{ color: #5a5650; font-size: 13px; margin-bottom: 16px; }}

        /* Search bar */
        .search-bar {{
            margin-bottom: 20px; display: flex; gap: 10px; align-items: center;
        }}
        .search-bar input {{
            flex: 1; padding: 12px 16px; border: 1px solid #1e2028; border-radius: 10px;
            background: #111318; color: #c8c4be; font-size: 15px;
        }}
        .search-bar input::placeholder {{ color: #4a4640; }}
        .search-bar input:focus {{ outline: none; border-color: #c49a6c; }}

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
        .filter-badge {{
            display: inline-flex; align-items: center; justify-content: center;
            background: #0a0b10; color: #c49a6c; font-size: 10px; font-weight: 700;
            min-width: 18px; height: 18px; border-radius: 9px; padding: 0 5px;
            margin-left: 4px;
        }}
        .filter-badge:empty {{ display: none; }}
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
        .card-pm2 {{ font-size: 12px; color: #5a5650; margin-bottom: 4px; }}
        .card-price-history {{
            display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
            margin-bottom: 6px; font-size: 11px; color: #7a3030;
        }}
        .ph-arrow {{ color: #5a5650; }}
        .card-predicted {{
            font-size: 11px; margin-bottom: 6px; display: flex; align-items: center; gap: 4px;
        }}
        .card-predicted .pred-label {{ color: #5a5650; }}
        .pred-under {{ color: #6aad7a; }}
        .pred-over {{ color: #7a3030; }}
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

        /* Favourites */
        .fav-btn {{
            position: absolute; top: 10px; right: 46px;
            background: rgba(0,0,0,0.5); border: none; cursor: pointer;
            width: 32px; height: 32px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-size: 18px;
            transition: all 0.15s; z-index: 2;
        }}
        .fav-btn:hover {{ background: rgba(0,0,0,0.8); transform: scale(1.1); }}
        .fav-btn.faved {{ color: #e25555; }}
        .fav-btn:not(.faved) {{ color: #555; }}
        .fav-count {{
            display: inline-flex; align-items: center; justify-content: center;
            background: #e25555; color: #fff; font-size: 10px; font-weight: 700;
            min-width: 16px; height: 16px; border-radius: 8px; padding: 0 4px;
            margin-left: 2px;
        }}
        .fav-count:empty {{ display: none; }}

        /* Badges */
        .badges {{ position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; }}
        .badge {{
            padding: 3px 8px; border-radius: 4px; font-size: 11px;
            font-weight: 600; text-transform: uppercase;
        }}
        .badge-new {{ background: #c49a6c; color: #0a0b10; }}
        .badge-drop {{ background: #7a3030; color: #ddd; }}
        .badge-offer {{ background: #c49a6c; color: #0a0b10; }}
        .badge-sold {{ background: #7a3030; color: #ddd; }}
        .card.card-sold {{ opacity: 0.65; }}
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

        /* Status pills */
        .status-pills {{
            display: flex; gap: 4px; align-items: center;
        }}
        .status-pills label {{
            font-size: 11px; font-weight: 600; color: #5a5650;
            margin-right: 4px; text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .status-pill {{
            padding: 5px 12px; border-radius: 14px; font-size: 12px;
            font-weight: 600; cursor: pointer; border: 1px solid #252530;
            background: transparent; color: #6b6762;
            transition: all 0.15s;
        }}
        .status-pill.active {{
            background: #c49a6c; color: #0a0b10; border-color: #c49a6c;
        }}
        .status-pill.active.pill-sold {{
            background: #7a3030; color: #ddd; border-color: #7a3030;
        }}
        .status-pill:hover {{ border-color: #c49a6c; }}

        /* Stadsdeel (borough) pills */
        .stadsdeel-pills {{
            display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; padding: 2px;
        }}
        .stadsdeel-pill {{
            padding: 6px 14px; border-radius: 14px; font-size: 13px;
            font-weight: 700; cursor: pointer; border: 2px solid #252530;
            background: transparent; color: #6b6762;
            transition: all 0.15s; white-space: nowrap;
        }}
        .stadsdeel-pill.sd-all {{
            background: #c49a6c; color: #0a0b10; border-color: #c49a6c;
        }}
        .stadsdeel-pill.sd-partial {{
            background: rgba(196, 154, 108, 0.3); color: #c49a6c;
            border-color: #c49a6c; border-style: dashed;
        }}
        .stadsdeel-pill.sd-none {{
            background: transparent; color: #6b6762; border-color: #252530;
        }}
        .stadsdeel-pill:hover {{ border-color: #c49a6c; }}

        /* Wijk pills */
        .wijk-pills {{
            display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 12px;
            max-height: 120px; overflow-y: auto; padding: 2px;
        }}
        .wijk-pill {{
            padding: 4px 10px; border-radius: 12px; font-size: 11px;
            font-weight: 600; cursor: pointer; border: 1.5px solid #252530;
            background: transparent; color: #6b6762;
            transition: all 0.15s; white-space: nowrap;
        }}
        .wijk-pill.wijk-all {{
            background: #c49a6c; color: #0a0b10; border-color: #c49a6c;
        }}
        .wijk-pill.wijk-partial {{
            background: rgba(196, 154, 108, 0.3); color: #c49a6c;
            border-color: #c49a6c; border-style: dashed;
        }}
        .wijk-pill.wijk-none {{
            background: transparent; color: #6b6762; border-color: #252530;
        }}
        .wijk-pill:hover {{ border-color: #c49a6c; }}

        /* Hood selector map */
        #hoodMap {{
            height: 350px; border-radius: 8px; border: 1px solid #1a1c24;
            margin-bottom: 16px;
        }}

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

        /* Modal */
        .modal-overlay {{
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
            z-index: 1000; overflow-y: auto; padding: 40px 20px;
            align-items: flex-start; justify-content: center;
        }}
        .modal-overlay.open {{ display: flex; }}
        .modal-content {{
            background: #111318; border-radius: 12px; max-width: 700px; width: 100%;
            border: 1px solid #252530; position: relative; animation: modalIn 0.2s ease;
        }}
        @keyframes modalIn {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: none; }} }}
        .modal-close {{
            position: absolute; top: 12px; right: 12px; background: rgba(0,0,0,0.6);
            border: none; color: #999; font-size: 24px; cursor: pointer;
            width: 36px; height: 36px; border-radius: 50%; z-index: 2;
            display: flex; align-items: center; justify-content: center;
        }}
        .modal-close:hover {{ color: #fff; background: rgba(0,0,0,0.8); }}
        .modal-img {{ width: 100%; max-height: 400px; object-fit: cover; border-radius: 12px 12px 0 0; }}
        .modal-body {{ padding: 24px; }}
        .modal-price {{ font-size: 28px; font-weight: 700; color: #c49a6c; }}
        .modal-address {{ font-size: 16px; color: #c8c4be; margin: 6px 0; }}
        .modal-grid {{
            display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
            gap: 10px; margin: 16px 0;
        }}
        .modal-grid .det {{ padding: 10px; }}
        .modal-section {{ margin-top: 16px; padding-top: 16px; border-top: 1px solid #1e2028; }}
        .modal-section h4 {{ color: #c49a6c; margin-bottom: 8px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.3px; }}
        .modal-row {{ display: flex; justify-content: space-between; align-items: center; margin: 6px 0; font-size: 14px; }}
        .modal-row .val {{ font-weight: 600; }}
        .residual-positive {{ color: #6aad7a; }}
        .residual-negative {{ color: #7a3030; }}
        .modal-actions {{ margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .modal-actions a.btn {{ text-decoration: none; display: inline-flex; align-items: center; }}

        @media (max-width: 768px) {{
            .modal-overlay {{ padding: 20px 10px; }}
            .modal-content {{ border-radius: 10px; }}
            .modal-img {{ max-height: 280px; }}
            .modal-body {{ padding: 16px; }}
            .modal-price {{ font-size: 24px; }}
        }}

        /* Empty state */
        .empty-state {{
            text-align: center; padding: 60px 20px; color: #5a5650; grid-column: 1 / -1;
        }}
        .empty-state h3 {{ color: #6b6762; margin-bottom: 8px; font-size: 18px; }}
        .empty-state p {{ font-size: 14px; margin-bottom: 16px; }}

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
            #hoodMap {{ height: 250px; }}
            .status-pills {{ flex-wrap: wrap; }}
        }}

        /* Back to top */
        .back-to-top {{
            position: fixed; bottom: 24px; right: 24px; width: 44px; height: 44px;
            border-radius: 50%; background: #c49a6c; color: #0a0b10; border: none;
            font-size: 20px; cursor: pointer; display: none; z-index: 999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            align-items: center; justify-content: center;
        }}
        .back-to-top.visible {{ display: flex; }}
        .back-to-top:hover {{ background: #a8845a; }}

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

    <div class="search-bar">
        <input type="text" id="searchInput" placeholder="Search by address, postcode, or neighbourhood..." autocomplete="off">
    </div>

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
                <option value="underpriced">Most underpriced (ML)</option>
            </select>
        </div>
        <div class="toggles">
            <label class="toggle"><input type="checkbox" id="fNewOnly"> New (24h)</label>
            <label class="toggle"><input type="checkbox" id="fDropOnly"> Price drops</label>
            <label class="toggle"><input type="checkbox" id="fFavOnly"> Saved <span class="fav-count" id="favCountBadge"></span></label>
        </div>
        <div class="status-pills">
            <label>Status</label>
            <button class="status-pill active" id="pillAvailable" onclick="toggleStatus('available')">Available</button>
            <button class="status-pill active" id="pillNegotiations" onclick="toggleStatus('negotiations')">Under Offer</button>
            <button class="status-pill pill-sold" id="pillSold" onclick="toggleStatus('sold')">Sold</button>
        </div>
        <button class="btn" onclick="applyFilters()">Filter <span class="filter-badge" id="filterBadge"></span></button>
        <button class="btn btn-ghost" onclick="resetFilters()">Reset</button>
        <button class="btn btn-ghost" id="hoodToggleBtn" onclick="toggleHoods()">Neighbourhoods</button>
        <div class="view-toggle">
            <button class="view-btn active" id="viewGrid" onclick="setView('grid')">Grid</button>
            <button class="view-btn" id="viewMap" onclick="setView('map')">Map</button>
        </div>
    </div>

    <div class="hood-panel" id="hoodPanel">
        <h3>Neighbourhood Selector</h3>
        <div class="stadsdeel-pills" id="stadsdeelPills"></div>
        <div class="wijk-pills" id="wijkPills"></div>
        <div id="hoodMap"></div>
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
    <div id="loadMore" style="height:1px;"></div>
    </div><!-- /gridContainer -->

    <div class="modal-overlay" id="modalOverlay" onclick="if(event.target===this)closeModal()">
        <div class="modal-content" id="modalContent"></div>
    </div>

    <button class="back-to-top" id="backToTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">&uarr;</button>

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
let excludedHoods = new Set(JSON.parse(localStorage.getItem('gc_excluded_hoods') || '[]'));
let favourites = new Set(JSON.parse(localStorage.getItem('gc_favourites') || '[]'));
let activeStatuses = new Set(['available', 'negotiations']);
let hoodSelectorMap = null;
let hoodMapMarkers = {{}};

// ── Init ──
function init() {{
    renderStats();
    populateHoodDropdown();
    renderHoodTable();
    updateFavCount();
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

function matchesSearch(l, searchTerm) {{
    const haystack = `${{l.address || ''}} ${{l.postcode || ''}} ${{l.neighbourhood || ''}} ${{l.city || ''}} ${{l.agent_name || ''}}`.toLowerCase();
    const words = searchTerm.split(/\\s+/).filter(Boolean);
    return words.every(w => haystack.includes(w));
}}

// ── Favourites ──
function toggleFav(globalId) {{
    if (favourites.has(globalId)) favourites.delete(globalId);
    else favourites.add(globalId);
    localStorage.setItem('gc_favourites', JSON.stringify([...favourites]));
    document.querySelectorAll(`.fav-btn[data-id="${{globalId}}"]`).forEach(btn => {{
        btn.classList.toggle('faved', favourites.has(globalId));
        btn.innerHTML = favourites.has(globalId) ? '&#9829;' : '&#9825;';
    }});
    updateFavCount();
}}
function updateFavCount() {{
    const el = document.getElementById('favCountBadge');
    if (el) el.textContent = favourites.size > 0 ? favourites.size : '';
}}

// ── Status toggles ──
function toggleStatus(status) {{
    if (activeStatuses.has(status)) activeStatuses.delete(status);
    else activeStatuses.add(status);
    const pillMap = {{ available: 'pillAvailable', negotiations: 'pillNegotiations', sold: 'pillSold' }};
    document.getElementById(pillMap[status]).classList.toggle('active', activeStatuses.has(status));
    applyFilters();
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
    const favOnly = document.getElementById('fFavOnly').checked;
    const searchTerm = (document.getElementById('searchInput').value || '').toLowerCase().trim();
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
        if (!activeStatuses.has(l.availability_status || 'available')) return false;
        if (excludedHoods.has(l.neighbourhood)) return false;
        if (hood && l.neighbourhood !== hood) return false;
        if (newOnly && !isNew(l)) return false;
        if (dropOnly && !hasDrop(l)) return false;
        if (favOnly && !favourites.has(l.global_id)) return false;
        if (searchTerm && !matchesSearch(l, searchTerm)) return false;
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
        underpriced: (a, b) => (b.residual || 0) - (a.residual || 0),
    }};
    filtered.sort(sorters[sort] || sorters.score);

    showing = 0;
    document.getElementById('grid').innerHTML = '';
    document.getElementById('showCount').textContent = '0';
    document.getElementById('totalCount').textContent = filtered.length;
    if (filtered.length === 0) {{
        document.getElementById('grid').innerHTML = `
            <div class="empty-state">
                <h3>No properties match your filters</h3>
                <p>Try adjusting your price range, area, or neighbourhood selection.</p>
                <button class="btn btn-ghost" onclick="resetFilters()">Reset all filters</button>
            </div>`;
        updateFilterBadge();
        return;
    }}
    loadMore();
    if (currentView === 'map') updateMap();
    updateFilterBadge();
}}

function updateFilterBadge() {{
    let count = 0;
    if (document.getElementById('fMinPrice').value) count++;
    if (document.getElementById('fMaxPrice').value) count++;
    if (document.getElementById('fMinArea').value) count++;
    if (document.getElementById('fMaxArea').value) count++;
    if (document.getElementById('fMinBed').value) count++;
    if (document.getElementById('fEnergy').value) count++;
    if (document.getElementById('fHood').value) count++;
    if (document.getElementById('fNewOnly').checked) count++;
    if (document.getElementById('fDropOnly').checked) count++;
    if (document.getElementById('fFavOnly').checked) count++;
    const search = document.getElementById('searchInput');
    if (search && search.value.trim()) count++;
    if (!activeStatuses.has('available') || !activeStatuses.has('negotiations') || activeStatuses.has('sold')) count++;
    if (excludedHoods.size > 0) count++;
    document.getElementById('filterBadge').textContent = count > 0 ? count : '';
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
    document.getElementById('fFavOnly').checked = false;
    document.getElementById('searchInput').value = '';
    activeStatuses = new Set(['available', 'negotiations']);
    document.getElementById('pillAvailable').classList.add('active');
    document.getElementById('pillNegotiations').classList.add('active');
    document.getElementById('pillSold').classList.remove('active');
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
}}

function createCard(l) {{
    const div = document.createElement('div');
    const isSold = l.availability_status === 'sold';
    const isOffer = l.availability_status === 'negotiations';
    div.className = 'card' + (isSold ? ' card-sold' : '');
    div.style.cursor = 'pointer';
    div.setAttribute('onclick', `openModal(${{l.global_id}})`);

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

    // Price history
    let phHtml = '';
    if (l.price_history && l.price_history.length > 0) {{
        const entries = l.price_history.slice(0, 3).map(h =>
            `&euro;${{h.old_price.toLocaleString()}} <span class="ph-arrow">&rarr;</span> &euro;${{h.new_price.toLocaleString()}} <span style="color:#5a5650">(${{h.date}})</span>`
        ).join(' ');
        phHtml = `<div class="card-price-history">${{entries}}</div>`;
    }}

    // ML prediction
    let predHtml = '';
    if (l.predicted_price) {{
        const diff = l.price_numeric - l.predicted_price;
        const diffPct = Math.abs((diff / l.predicted_price) * 100).toFixed(0);
        const cls = diff > 0 ? 'pred-over' : 'pred-under';
        const arrow = diff > 0 ? '&uarr;' : '&darr;';
        predHtml = `<div class="card-predicted"><span class="pred-label">ML:</span> <span class="${{cls}}">&euro;${{Math.round(l.predicted_price).toLocaleString()}} (${{arrow}}${{diffPct}}%)</span></div>`;
    }}

    div.innerHTML = `
        <div class="badges">
            ${{isSold ? '<span class="badge badge-sold">Sold</span>' : ''}}
            ${{isOffer ? '<span class="badge badge-offer">Under Offer</span>' : ''}}
            ${{isN ? '<span class="badge badge-new">New</span>' : ''}}
            ${{drop ? `<span class="badge badge-drop">-${{dropPct}}%</span>` : ''}}
        </div>
        <button class="fav-btn ${{favourites.has(l.global_id) ? 'faved' : ''}}" data-id="${{l.global_id}}" onclick="event.stopPropagation(); toggleFav(${{l.global_id}})">${{favourites.has(l.global_id) ? '&#9829;' : '&#9825;'}}</button>
        <span class="badge-score ${{sc}}" title="Score: ${{l.score}}&#10;vs neighbourhood: ${{l.score_details?.vs_neighbourhood_pct ?? 'n/a'}}%&#10;vs city: ${{l.score_details?.vs_city_pct ?? 'n/a'}}%&#10;Days on market: ${{l.score_details?.days_on_market ?? '?'}}">${{l.score?.toFixed(1) || '—'}}</span>
        <div class="card-img">${{l.image_url ? `<img src="${{l.image_url}}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}}</div>
        <div class="card-body">
            <div class="card-price">&euro;${{l.price_numeric.toLocaleString()}}${{prevHtml}}</div>
            <div class="card-address">${{l.address || 'Unknown'}}</div>
            <div class="card-pm2">${{pm2}}</div>
            ${{phHtml}}
            ${{predHtml}}
            <div class="card-details">
                <div class="det"><div class="det-label">m&sup2;</div><div class="det-value">${{l.living_area || '—'}}</div></div>
                <div class="det"><div class="det-label">Beds</div><div class="det-value">${{l.bedrooms ?? '—'}}</div></div>
                <div class="det"><div class="det-label">Energy</div><div class="det-value ${{elClass}}">${{l.energy_label || '—'}}</div></div>
            </div>
            <div class="card-meta">
                <span>${{l.neighbourhood || l.city || ''}}</span>
                <a href="${{l.detail_url}}" target="_blank" rel="noopener" onclick="event.stopPropagation()">View listing &rarr;</a>
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
    const panel = document.getElementById('hoodPanel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {{
        setTimeout(() => {{
            initHoodMap();
            hoodSelectorMap.invalidateSize();
        }}, 100);
    }}
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
    updateHoodMapMarker(hood);
    updateAllWijkPills();
    updateAllStadsdeelPills();
    saveExcludedHoods();
    populateHoodDropdown();
    applyFilters();
}}

function hoodSelectAll(include) {{
    excludedHoods = include ? new Set() : new Set(Object.keys(NEIGHBOURHOOD_STATS));
    saveExcludedHoods();
    renderHoodTable();
    updateAllHoodMapMarkers();
    updateAllWijkPills();
    updateAllStadsdeelPills();
    populateHoodDropdown();
    applyFilters();
}}

function hoodInvert() {{
    const all = Object.keys(NEIGHBOURHOOD_STATS);
    const newExcluded = new Set(all.filter(h => !excludedHoods.has(h)));
    excludedHoods = newExcluded;
    saveExcludedHoods();
    renderHoodTable();
    updateAllHoodMapMarkers();
    updateAllWijkPills();
    updateAllStadsdeelPills();
    populateHoodDropdown();
    applyFilters();
}}

function saveExcludedHoods() {{
    localStorage.setItem('gc_excluded_hoods', JSON.stringify([...excludedHoods]));
    updateHoodExcludeCount();
}}

function updateHoodExcludeCount() {{
    const n = excludedHoods.size;
    const countEl = document.getElementById('hoodExcludeCount');
    const btn = document.getElementById('hoodToggleBtn');
    countEl.textContent = n > 0 ? `${{n}} hidden` : '';
    btn.textContent = n > 0 ? `Neighbourhoods (${{n}} hidden)` : 'Neighbourhoods';
}}

// ── Hood selector map ──
function initHoodMap() {{
    if (hoodSelectorMap) return;
    renderStadsdeelPills();
    renderWijkPills();
    hoodSelectorMap = L.map('hoodMap').setView([52.3676, 4.9041], 12);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '',
        subdomains: 'abcd',
        maxZoom: 19
    }}).addTo(hoodSelectorMap);

    // Create a circle for every neighbourhood in MAP_DATA
    Object.entries(MAP_DATA).forEach(([name, d]) => {{
        const included = !excludedHoods.has(name);
        const marker = L.circleMarker([d.lat, d.lng], {{
            radius: 10,
            fillColor: included ? '#c49a6c' : 'transparent',
            color: included ? '#c49a6c' : '#7a3030',
            weight: included ? 1 : 2,
            fillOpacity: included ? 0.7 : 0,
            opacity: 0.9,
        }}).addTo(hoodSelectorMap);
        marker.bindTooltip(name, {{ className: 'hood-tooltip' }});
        marker.on('click', () => onHoodMapClick(name));
        hoodMapMarkers[name] = marker;
    }});
}}

function onHoodMapClick(name) {{
    if (excludedHoods.has(name)) excludedHoods.delete(name);
    else excludedHoods.add(name);
    updateHoodMapMarker(name);
    updateAllWijkPills();
    updateAllStadsdeelPills();
    // Sync table checkbox
    const cb = document.querySelector(`#hoodTable input[data-hood="${{name}}"]`);
    if (cb) {{
        cb.checked = !excludedHoods.has(name);
        cb.closest('tr').classList.toggle('excluded', excludedHoods.has(name));
    }}
    saveExcludedHoods();
    populateHoodDropdown();
    applyFilters();
}}

function updateHoodMapMarker(name) {{
    const marker = hoodMapMarkers[name];
    if (!marker) return;
    const included = !excludedHoods.has(name);
    marker.setStyle({{
        fillColor: included ? '#c49a6c' : 'transparent',
        color: included ? '#c49a6c' : '#7a3030',
        weight: included ? 1 : 2,
        fillOpacity: included ? 0.7 : 0,
    }});
}}

function updateAllHoodMapMarkers() {{
    Object.keys(hoodMapMarkers).forEach(updateHoodMapMarker);
}}

// ── Stadsdeel (borough) pills ──
const stadsdeelGroups = {{}};  // stadsdeelName → [buurtName, ...]
const wijkGroups = {{}};  // wijkName → [buurtName, ...]
const wijkToStadsdeel = {{}};  // wijkName → stadsdeelName
(function buildGroups() {{
    Object.entries(MAP_DATA).forEach(([name, d]) => {{
        const wijk = d.wijk || '(unknown)';
        const sd = d.stadsdeel || '(unknown)';
        if (!wijkGroups[wijk]) wijkGroups[wijk] = [];
        wijkGroups[wijk].push(name);
        if (!stadsdeelGroups[sd]) stadsdeelGroups[sd] = [];
        stadsdeelGroups[sd].push(name);
        wijkToStadsdeel[wijk] = sd;
    }});
}})();

function getStadsdeelState(sdName) {{
    const buurten = stadsdeelGroups[sdName] || [];
    if (buurten.length === 0) return 'none';
    const excludedCount = buurten.filter(b => excludedHoods.has(b)).length;
    if (excludedCount === 0) return 'all';
    if (excludedCount === buurten.length) return 'none';
    return 'partial';
}}

function renderStadsdeelPills() {{
    const container = document.getElementById('stadsdeelPills');
    const sdNames = Object.keys(stadsdeelGroups).sort();
    container.innerHTML = sdNames.map(sd => {{
        const state = getStadsdeelState(sd);
        const count = stadsdeelGroups[sd].length;
        return `<button class="stadsdeel-pill sd-${{state}}" data-sd="${{sd}}" onclick="toggleStadsdeel('${{sd.replace(/'/g, "\\\\'")}}')">${{sd}} (${{count}})</button>`;
    }}).join('');
}}

function toggleStadsdeel(sdName) {{
    const buurten = stadsdeelGroups[sdName] || [];
    const state = getStadsdeelState(sdName);
    if (state === 'none') {{
        buurten.forEach(b => excludedHoods.delete(b));
    }} else {{
        buurten.forEach(b => excludedHoods.add(b));
    }}
    saveExcludedHoods();
    renderHoodTable();
    updateAllHoodMapMarkers();
    updateAllWijkPills();
    updateAllStadsdeelPills();
    populateHoodDropdown();
    applyFilters();
}}

function updateAllStadsdeelPills() {{
    document.querySelectorAll('.stadsdeel-pill').forEach(pill => {{
        const sd = pill.dataset.sd;
        const state = getStadsdeelState(sd);
        pill.className = `stadsdeel-pill sd-${{state}}`;
    }});
}}

function getWijkState(wijkName) {{
    const buurten = wijkGroups[wijkName] || [];
    if (buurten.length === 0) return 'none';
    const excludedCount = buurten.filter(b => excludedHoods.has(b)).length;
    if (excludedCount === 0) return 'all';
    if (excludedCount === buurten.length) return 'none';
    return 'partial';
}}

function renderWijkPills() {{
    const container = document.getElementById('wijkPills');
    const wijkNames = Object.keys(wijkGroups).sort();
    container.innerHTML = wijkNames.map(wijk => {{
        const state = getWijkState(wijk);
        const count = wijkGroups[wijk].length;
        return `<button class="wijk-pill wijk-${{state}}" data-wijk="${{wijk}}" onclick="toggleWijk('${{wijk.replace(/'/g, "\\\\'")}}')">${{wijk}} (${{count}})</button>`;
    }}).join('');
}}

function toggleWijk(wijkName) {{
    const buurten = wijkGroups[wijkName] || [];
    const state = getWijkState(wijkName);
    if (state === 'none') {{
        buurten.forEach(b => excludedHoods.delete(b));
    }} else {{
        buurten.forEach(b => excludedHoods.add(b));
    }}
    saveExcludedHoods();
    renderHoodTable();
    updateAllHoodMapMarkers();
    updateAllWijkPills();
    updateAllStadsdeelPills();
    populateHoodDropdown();
    applyFilters();
}}

function updateAllWijkPills() {{
    document.querySelectorAll('.wijk-pill').forEach(pill => {{
        const wijk = pill.dataset.wijk;
        const state = getWijkState(wijk);
        pill.className = `wijk-pill wijk-${{state}}`;
    }});
}}

// ── Main map ──
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

// ── Modal ──
function openModal(globalId) {{
    const l = LISTINGS.find(x => x.global_id === globalId);
    if (!l) return;
    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');

    const isFaved = favourites.has(l.global_id);
    const drop = hasDrop(l);
    const dropPct = drop ? Math.round((1 - l.price_numeric / l.previous_price) * 100) : 0;
    const elBase = (l.energy_label || '').replace(/[+]/g, '');

    // Price history section
    let historyHtml = '';
    if (l.price_history && l.price_history.length > 0) {{
        historyHtml = `<div class="modal-section"><h4>Price History</h4>`;
        l.price_history.forEach(h => {{
            historyHtml += `<div class="modal-row"><span>${{h.date}}</span><span>&euro;${{h.old_price.toLocaleString()}} &rarr; &euro;${{h.new_price.toLocaleString()}}</span></div>`;
        }});
        historyHtml += `</div>`;
    }}

    // ML prediction section
    let predictedHtml = '';
    if (l.predicted_price) {{
        const diff = l.price_numeric - l.predicted_price;
        const diffPct = ((diff / l.predicted_price) * 100).toFixed(1);
        const cls = diff > 0 ? 'residual-negative' : 'residual-positive';
        const label = diff > 0 ? 'overpriced' : 'underpriced';
        predictedHtml = `<div class="modal-section"><h4>ML Price Estimate</h4>
            <div class="modal-row"><span>Predicted</span><span class="val" style="color:#c49a6c">&euro;${{Math.round(l.predicted_price).toLocaleString()}}</span></div>
            <div class="modal-row"><span>Asking</span><span class="val">&euro;${{l.price_numeric.toLocaleString()}}</span></div>
            <div class="modal-row"><span>Difference</span><span class="val ${{cls}}">&euro;${{Math.abs(Math.round(diff)).toLocaleString()}} (${{Math.abs(diffPct)}}% ${{label}})</span></div>
        </div>`;
    }}

    // Score breakdown section
    let scoreHtml = '';
    if (l.score_details) {{
        const sd = l.score_details;
        scoreHtml = `<div class="modal-section"><h4>Deal Score Breakdown</h4>
            <div class="modal-row"><span>vs Neighbourhood avg</span><span class="val">${{sd.vs_neighbourhood_pct != null ? sd.vs_neighbourhood_pct + '%' : 'n/a'}}</span></div>
            <div class="modal-row"><span>vs City avg</span><span class="val">${{sd.vs_city_pct != null ? sd.vs_city_pct + '%' : 'n/a'}}</span></div>
            <div class="modal-row"><span>Days on market</span><span class="val">${{sd.days_on_market ?? '?'}}</span></div>
            <div class="modal-row"><span><strong>Total score</strong></span><span class="val" style="color:#c49a6c"><strong>${{l.score?.toFixed(1) || '--'}}</strong></span></div>
        </div>`;
    }}

    content.innerHTML = `
        <button class="modal-close" onclick="closeModal()">&times;</button>
        ${{l.image_url ? `<img class="modal-img" src="${{l.image_url}}" referrerpolicy="no-referrer">` : ''}}
        <div class="modal-body">
            <div class="modal-price">&euro;${{l.price_numeric.toLocaleString()}}${{drop ? ` <span class="card-prev-price">&euro;${{l.previous_price.toLocaleString()}} (-${{dropPct}}%)</span>` : ''}}</div>
            <div class="modal-address">${{l.address || 'Unknown'}}</div>
            <div style="color:#5a5650;font-size:13px;margin-bottom:4px">${{l.neighbourhood || ''}}${{l.postcode ? ' &middot; ' + l.postcode : ''}}${{l.city ? ' &middot; ' + l.city : ''}}</div>
            <div class="modal-grid">
                <div class="det"><div class="det-label">Area</div><div class="det-value">${{l.living_area || '--'}} m&sup2;</div></div>
                <div class="det"><div class="det-label">Bedrooms</div><div class="det-value">${{l.bedrooms ?? '--'}}</div></div>
                <div class="det"><div class="det-label">Energy</div><div class="det-value el-${{elBase}}">${{l.energy_label || '--'}}</div></div>
                <div class="det"><div class="det-label">Type</div><div class="det-value">${{l.object_type || '--'}}</div></div>
                <div class="det"><div class="det-label">EUR/m&sup2;</div><div class="det-value">${{l.price_m2 ? '&euro;' + Math.round(l.price_m2).toLocaleString() : '--'}}</div></div>
                <div class="det"><div class="det-label">Construction</div><div class="det-value">${{l.construction_type || '--'}}</div></div>
                <div class="det"><div class="det-label">Agent</div><div class="det-value" style="font-size:11px">${{l.agent_name || '--'}}</div></div>
                <div class="det"><div class="det-label">Plot</div><div class="det-value">${{l.plot_area ? l.plot_area + ' m&sup2;' : '--'}}</div></div>
            </div>
            ${{predictedHtml}}
            ${{scoreHtml}}
            ${{historyHtml}}
            <div class="modal-actions">
                <a href="${{l.detail_url}}" target="_blank" rel="noopener" class="btn">View Listing &rarr;</a>
                <button class="btn btn-ghost" onclick="toggleFav(${{l.global_id}}); openModal(${{l.global_id}});">
                    ${{isFaved ? '&#9829; Saved' : '&#9825; Save'}}
                </button>
            </div>
        </div>`;

    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
}}

function closeModal() {{
    document.getElementById('modalOverlay').classList.remove('open');
    document.body.style.overflow = '';
}}

document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

// ── Back to top ──
window.addEventListener('scroll', () => {{
    document.getElementById('backToTop').classList.toggle('visible', window.scrollY > 500);
}});

// ── Auto-filter on Enter / input change ──
document.addEventListener('DOMContentLoaded', () => {{
    let debounceTimer;
    const debouncedFilter = () => {{
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(applyFilters, 400);
    }};
    document.querySelectorAll('.filters input, .filters select').forEach(el => {{
        el.addEventListener('keydown', e => {{ if (e.key === 'Enter') applyFilters(); }});
        if (el.tagName === 'SELECT' || el.type === 'checkbox') {{
            el.addEventListener('change', applyFilters);
        }}
        if (el.type === 'number') {{
            el.addEventListener('input', debouncedFilter);
        }}
    }});
    // Search bar with fast debounce
    let searchTimeout;
    document.getElementById('searchInput').addEventListener('input', () => {{
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 250);
    }});
    // Infinite scroll
    const loadMoreObserver = new IntersectionObserver(entries => {{
        if (entries[0].isIntersecting && showing < filtered.length) {{
            loadMore();
        }}
    }}, {{ rootMargin: '400px' }});
    init();
    loadMoreObserver.observe(document.getElementById('loadMore'));
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
