#!/usr/bin/env python3
"""
Ground Control — Interactive terminal UI
"""

import sqlite3
import os
import sys
from pathlib import Path

# Try rich, fall back to basic if not available
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

DB_PATH = Path(__file__).parent / "ground_control.db"

def get_db():
    """Connect to database"""
    db_path = str(DB_PATH).replace("~", str(Path.home()))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_listings(filters=None):
    """Get listings with optional filters"""
    conn = get_db()
    c = conn.cursor()
    
    query = """
        SELECT address, city, postcode, neighbourhood, price, price_numeric,
               living_area, bedrooms, energy_label, object_type, 
               construction_type, agent_name, detail_url, image_url, is_active
        FROM listings 
        WHERE is_active = 1
    """
    params = []
    
    if filters:
        if filters.get('min_price'):
            query += " AND price_numeric >= ?"
            params.append(filters['min_price'])
        if filters.get('max_price'):
            query += " AND price_numeric <= ?"
            params.append(filters['max_price'])
        if filters.get('min_area'):
            query += " AND living_area >= ?"
            params.append(filters['min_area'])
        if filters.get('max_area'):
            query += " AND living_area <= ?"
            params.append(filters['max_area'])
        if filters.get('min_bedrooms'):
            query += " AND bedrooms >= ?"
            params.append(filters['min_bedrooms'])
    
    query += " ORDER BY price_numeric ASC"
    
    c.execute(query, params)
    results = c.fetchall()
    conn.close()
    return [dict(row) for row in results]

def calculate_price_per_m2(listing):
    """Calculate price per m²"""
    if listing.get('living_area') and listing['living_area'] > 0:
        return listing['price_numeric'] / listing['living_area']
    return 0

def format_price(price):
    """Format price with € and k"""
    if price >= 1000:
        return f"€{price:,.0f}".replace(",", ".")
    return f"€{price}"

def show_table(listings, page=0, per_page=20):
    """Display listings in a table"""
    if RICH_AVAILABLE:
        console = Console()
        
        table = Table(title=f"🏠 Ground Control Listings ({len(listings)} found)", box=box.ROUNDED)
        table.add_column("#", style="dim", width=4)
        table.add_column("Address", style="cyan", width=25)
        table.add_column("Price", style="green", width=10)
        table.add_column("m²", justify="right", width=6)
        table.add_column("Bed", justify="right", width=4)
        table.add_column("€/m²", justify="right", width=8)
        table.add_column("Energy", width=7)
        table.add_column("Type", width=12)
        
        start = page * per_page
        end = start + per_page
        page_items = listings[start:end]
        
        for i, h in enumerate(page_items, start + 1):
            price_m2 = calculate_price_per_m2(h)
            price_m2_str = f"€{price_m2:,.0f}".replace(",", ".") if price_m2 else "N/A"
            
            table.add_row(
                str(i),
                h.get('address', 'N/A')[:22],
                format_price(h.get('price_numeric', 0)),
                str(h.get('living_area', '-')),
                str(h.get('bedrooms', '-')),
                price_m2_str,
                h.get('energy_label', '-'),
                h.get('object_type', '-')[:10]
            )
        
        console.print(table)
        
        # Navigation
        total_pages = (len(listings) - 1) // per_page
        console.print(f"\n[dim]Page {page + 1}/{total_pages + 1} | Press N for next, P for previous, Q to quit[/dim]")
        
    else:
        # Basic table view
        print(f"\n{'#':<4} {'Address':<25} {'Price':<12} {'m²':<6} {'Bed':<5} {'€/m²':<8} {'Energy':<8} {'Type':<12}")
        print("-" * 90)
        
        start = page * per_page
        end = start + per_page
        
        for i, h in enumerate(listings[start:end], start + 1):
            price_m2 = calculate_price_per_m2(h)
            price_m2_str = f"€{price_m2:,.0f}".replace(",", ".") if price_m2 else "N/A"
            
            print(f"{i:<4} {h.get('address', 'N/A')[:22]:<25} {format_price(h.get('price_numeric', 0)):12} {str(h.get('living_area', '-')):<6} {str(h.get('bedrooms', '-')):<5} {price_m2_str:<8} {h.get('energy_label', '-'):<8} {h.get('object_type', '-')[:12]}")

def show_details(listing):
    """Show full details of a listing"""
    if RICH_AVAILABLE:
        console = Console()
        
        price_m2 = calculate_price_per_m2(listing)
        
        content = f"""
[cyan]Address:[/cyan] {listing.get('address', 'N/A')}
[cyan]City:[/cyan] {listing.get('city', 'N/A')}
[cyan]Postcode:[/cyan] {listing.get('postcode', 'N/A')}
[cyan]Neighbourhood:[/cyan] {listing.get('neighbourhood', 'N/A')}

[green]Price:[/green] {listing.get('price', 'N/A')}
[green]Price/m²:[/green] €{price_m2:,.0f} per m²

[yellow]Living Area:[/yellow] {listing.get('living_area', 'N/A')} m²
[yellow]Plot Area:[/yellow] {listing.get('plot_area', 'N/A')} m²
[yellow]Bedrooms:[/yellow] {listing.get('bedrooms', 'N/A')}

[magenta]Energy Label:[/magenta] {listing.get('energy_label', 'N/A')}
[magenta]Object Type:[/magenta] {listing.get('object_type', 'N/A')}
[magenta]Construction:[/magenta] {listing.get('construction_type', 'N/A')}

[blue]Agent:[/blue] {listing.get('agent_name', 'N/A')}

[link]{listing.get('detail_url', 'N/A')}[/link]
"""
        console.print(Panel(content, title="🏠 House Details", border_style="cyan"))
    else:
        print("\n" + "=" * 50)
        print("HOUSE DETAILS")
        print("=" * 50)
        for k, v in listing.items():
            if v:
                print(f"{k}: {v}")
        print("=" * 50)

def interactive_viewer():
    """Main interactive loop"""
    listings = get_listings()
    page = 0
    per_page = 20
    
    if not listings:
        print("No listings found!")
        return
    
    while True:
        show_table(listings, page, per_page)
        
        if RICH_AVAILABLE:
            choice = Prompt.ask("\n[bold]Choose[/bold]", choices=['n', 'p', 'q', 'd', 'f'], default='q')
        else:
            choice = input("\nChoose (n=next, p=prev, d=details, f=filter, q=quit): ").lower().strip()
        
        if choice == 'q':
            break
        elif choice == 'n':
            if (page + 1) * per_page < len(listings):
                page += 1
        elif choice == 'p':
            if page > 0:
                page -= 1
        elif choice == 'd':
            # Get listing number
            if RICH_AVAILABLE:
                num = Prompt.ask("Which listing #", default="1")
            else:
                num = input("Which listing #: ").strip() or "1"
            
            try:
                idx = int(num) - 1
                if 0 <= idx < len(listings):
                    show_details(listings[idx])
                else:
                    print("Invalid number")
            except ValueError:
                print("Please enter a number")
        elif choice == 'f':
            # Filter
            print("\n--- Filters ---")
            filters = {}
            
            if RICH_AVAILABLE:
                min_p = Prompt.ask("Min price (€)", default="")
                max_p = Prompt.ask("Max price (€)", default="")
                min_a = Prompt.ask("Min area (m²)", default="")
                max_a = Prompt.ask("Max area (m²)", default="")
                min_b = Prompt.ask("Min bedrooms", default="")
            else:
                min_p = input("Min price (€): ").strip()
                max_p = input("Max price (€): ").strip()
                min_a = input("Min area (m²): ").strip()
                max_a = input("Max area (m²): ").strip()
                min_b = input("Min bedrooms: ").strip()
            
            filters['min_price'] = int(min_p) if min_p else None
            filters['max_price'] = int(max_p) if max_p else None
            filters['min_area'] = int(min_a) if min_a else None
            filters['max_area'] = int(max_a) if max_a else None
            filters['min_bedrooms'] = int(min_b) if min_b else None
            
            filters = {k: v for k, v in filters.items() if v}
            
            if filters:
                listings = get_listings(filters)
                page = 0
                print(f"\n[Filtered to {len(listings)} listings]")

if __name__ == '__main__':
    interactive_viewer()
