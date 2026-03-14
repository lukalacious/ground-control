#!/usr/bin/env python3
"""
Generate a static postcode area heatmap (no map tiles needed).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ground_control.db"

def get_postcode_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("""
        SELECT 
            substr(postcode, 1, 4) as area,
            COUNT(*) as count,
            AVG(price_numeric) as avg_price
        FROM listings 
        WHERE is_active = 1 AND postcode != ''
        GROUP BY substr(postcode, 1, 4)
        ORDER BY count DESC
    """).fetchall()
    
    conn.close()
    return [dict(r) for r in rows]


def generate_html(stats):
    stats = sorted(stats, key=lambda x: x['count'], reverse=True)
    
    total_listings = sum(s['count'] for s in stats)
    with_prices = sum(1 for s in stats if s['avg_price'] and s['avg_price'] > 0)
    
    rows = []
    for s in stats[:25]:
        area = s['area']
        count = s['count']
        avg = s['avg_price'] or 0
        
        if avg > 0:
            if avg < 350000:
                color = '#22c55e'
            elif avg < 500000:
                color = '#f97316'
            else:
                color = '#ef4444'
            price_str = f"€{int(avg):,}"
        else:
            color = '#6b7280'
            price_str = "<span class='no-price'>enriching...</span>"
        
        rows.append(f"""
        <tr style="background: {color}15; border-bottom: 1px solid #eee;">
            <td style="padding: 10px; font-weight: bold;">{area}</td>
            <td style="padding: 10px; text-align: center;">{count}</td>
            <td style="padding: 10px;">{price_str}</td>
        </tr>
        """)
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Ground Control - Postcode Areas</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 20px; background: #f0f2f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #1e3a5f, #2d5a87); color: white; padding: 25px; }}
        h1 {{ margin: 0; font-size: 24px; }}
        .subtitle {{ opacity: 0.8; margin-top: 5px; }}
        .stats {{ display: flex; gap: 20px; margin-top: 15px; }}
        .stat {{ background: rgba(255,255,255,0.1); padding: 10px 15px; border-radius: 6px; }}
        .stat-value {{ font-size: 20px; font-weight: bold; }}
        .stat-label {{ font-size: 11px; opacity: 0.8; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f8f9fa; padding: 12px 10px; text-align: left; font-size: 12px; color: #666; text-transform: uppercase; }}
        .no-price {{ color: #999; font-style: italic; }}
        .legend {{ display: flex; gap: 15px; padding: 15px 25px; background: #f8f9fa; font-size: 12px; }}
        .legend-item {{ display: flex; align-items: center; gap: 6px; }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏠 Ground Control</h1>
            <div class="subtitle">Amsterdam - Postcode Areas</div>
            <div class="stats">
                <div class="stat"><div class="stat-value">{len(stats)}</div><div class="stat-label">Areas</div></div>
                <div class="stat"><div class="stat-value">{total_listings}</div><div class="stat-label">Listings</div></div>
                <div class="stat"><div class="stat-value">{with_prices}</div><div class="stat-label">With Prices</div></div>
            </div>
        </div>
        <table>
            <tr><th>Postcode</th><th style="text-align:center">#</th><th>Avg Price</th></tr>
            {''.join(rows)}
        </table>
        <div class="legend">
            <div class="legend-item"><div class="dot" style="background:#22c55e"></div>&lt;€350k</div>
            <div class="legend-item"><div class="dot" style="background:#f97316"></div>€350-500k</div>
            <div class="legend-item"><div class="dot" style="background:#ef4444"></div>&gt;€500k</div>
            <div class="legend-item"><div class="dot" style="background:#6b7280"></div>Pending</div>
        </div>
    </div>
</body>
</html>"""
    return html


def main():
    stats = get_postcode_stats()
    print(f"Found {len(stats)} postcode areas")
    
    html = generate_html(stats)
    output = Path(__file__).parent / "postcode_heatmap.html"
    output.write_text(html)
    print(f"Saved to: {output}")


if __name__ == "__main__":
    main()
