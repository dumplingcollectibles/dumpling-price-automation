"""
DUMPLING COLLECTIBLES - Bulk Inventory Upload

Upload multiple cards from CSV file with:
- Validation and error reporting
- Fuzzy matching for typos
- Auto-product creation from API
- Duplicate detection
- Progress tracking
- Shopify sync

Usage:
    python add_inventory_bulk.py filename.csv
"""

import csv
import sys
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import requests
from datetime import datetime
import math
import time

# Import our validator module
import csv_validator

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')
POKEMONTCG_API_URL = os.getenv('POKEMONTCG_API_URL', 'https://api.pokemontcg.io/v2')
TCG_API_KEY = os.getenv('TCG_API_KEY')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"

# Pricing config
USD_TO_CAD = 1.35
MARKUP = 1.10


def round_up_to_nearest_50_cents(amount):
    """Round up to nearest $0.50"""
    return math.ceil(amount * 2) / 2


def fetch_card_from_api(set_code, card_number):
    """
    Fetch card data from PokemonTCG API
    Returns: card_data dict or None
    """
    url = f"{POKEMONTCG_API_URL}/cards"
    headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
    params = {"q": f"set.id:{set_code} number:{card_number}"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            cards = data.get('data', [])
            
            if cards:
                return cards[0]
        
        return None
        
    except Exception as e:
        print(f"      ⚠️  API error: {str(e)[:50]}")
        return None


def extract_market_price(api_card):
    """Extract market price from API card"""
    tcgplayer = api_card.get('tcgplayer', {})
    prices = tcgplayer.get('prices', {})
    
    for price_type in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil']:
        if price_type in prices:
            price_data = prices[price_type]
            market = price_data.get('market') or price_data.get('mid') or price_data.get('low')
            if market and market > 0:
                return float(market)
    
    return 50.00  # Default if no price found


def create_card_in_database(api_card, market_price_usd):
    """
    Add new card to database from API data
    Returns: card_id or None
    """
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        base_market_cad = market_price_usd * USD_TO_CAD
        nm_selling_price = round_up_to_nearest_50_cents(base_market_cad * MARKUP)
        
        # Insert card
        cursor.execute("""
            INSERT INTO cards (
                external_ids, name, set_code, set_name, number,
                variant, language, rarity, supertype, img_url, release_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name, set_code, number, variant, language)
            DO UPDATE SET external_ids = EXCLUDED.external_ids, updated_at = NOW()
            RETURNING id
        """, (
            Json({'pokemontcg_io': api_card['id']}),
            api_card['name'],
            api_card['set']['id'],
            api_card['set']['name'],
            api_card['number'],
            'Normal',
            'English',
            api_card.get('rarity', 'Unknown'),
            api_card.get('supertype', 'Unknown'),
            api_card['images']['large'],
            api_card['set']['releaseDate']
        ))
        
        card_id = cursor.fetchone()[0]
        
        # Create product
        handle = f"{api_card['name']}-{api_card['set']['id']}-{api_card['number']}".lower()
        handle = handle.replace(' ', '-').replace("'", '').replace('!', '').replace('.', '')
        
        cursor.execute("""
            INSERT INTO products (card_id, handle, product_type, status, tags)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (card_id, handle, 'Single', 'draft', [api_card['set']['name'], api_card['name']]))
        
        product_result = cursor.fetchone()
        if not product_result:
            # Product already exists, get it
            cursor.execute("SELECT id FROM products WHERE card_id = %s", (card_id,))
            product_result = cursor.fetchone()
        
        product_id = product_result[0]
        
        # Create variants for all conditions
        conditions = ['NM', 'LP', 'MP', 'HP', 'DMG']
        condition_multipliers = {'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35}
        
        for condition in conditions:
            sku = f"{api_card['set']['id'].upper()}-{api_card['number']}-{condition}"
            selling_price = nm_selling_price if condition == 'NM' else round(nm_selling_price * condition_multipliers[condition], 2)
            
            cursor.execute("""
                INSERT INTO variants (product_id, condition, sku, inventory_qty, market_price, price_cad)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (sku) DO NOTHING
            """, (product_id, condition, sku, 0, base_market_cad, selling_price))
        
        conn.commit()
        return card_id
        
    except Exception as e:
        conn.rollback()
        print(f"      ❌ Database error: {str(e)[:100]}")
        return None
        
    finally:
        cursor.close()
        conn.close()


def get_variant_info(card_id, condition):
    """Get variant information"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                v.id as variant_id,
                v.condition,
                v.sku,
                v.inventory_qty,
                v.price_cad,
                v.cost_basis_avg,
                v.total_units_purchased,
                v.shopify_variant_id,
                p.id as product_id
            FROM variants v
            JOIN products p ON p.id = v.product_id
            WHERE p.card_id = %s AND v.condition = %s
        """, (card_id, condition))
        
        return cursor.fetchone()
        
    finally:
        cursor.close()
        conn.close()


def calculate_new_wac(old_qty, old_wac, new_qty, new_cost):
    """Calculate weighted average cost"""
    if old_wac is None or old_qty == 0:
        return new_cost
    
    old_total_value = old_qty * float(old_wac)
    new_total_value = new_qty * new_cost
    combined_value = old_total_value + new_total_value
    combined_qty = old_qty + new_qty
    
    return round(combined_value / combined_qty, 2)


def update_inventory(variant_id, new_qty, new_wac, total_units):
    """Update variant inventory"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE variants
            SET 
                inventory_qty = %s,
                cost_basis_avg = %s,
                total_units_purchased = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (new_qty, new_wac, total_units, variant_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        return False
        
    finally:
        cursor.close()
        conn.close()


def log_transaction(variant_id, quantity, unit_cost, source, notes):
    """Log inventory transaction"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO inventory_transactions (
                variant_id, transaction_type, quantity, unit_cost,
                reference_type, notes
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (variant_id, 'purchase', quantity, unit_cost, 'bulk_upload', notes))
        
        transaction_id = cursor.fetchone()[0]
        conn.commit()
        return transaction_id
        
    except Exception as e:
        conn.rollback()
        return None
        
    finally:
        cursor.close()
        conn.close()


def sync_to_shopify(shopify_variant_id, new_qty):
    """Sync inventory to Shopify"""
    if not SHOPIFY_ACCESS_TOKEN or not SHOPIFY_LOCATION_ID or not shopify_variant_id:
        return False
    
    try:
        # Get inventory item ID
        response = requests.get(
            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{shopify_variant_id}.json",
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN},
            timeout=10
        )
        
        if response.status_code != 200:
            return False
        
        inventory_item_id = response.json()['variant']['inventory_item_id']
        
        # Update inventory
        response = requests.post(
            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels/set.json",
            json={
                "location_id": int(SHOPIFY_LOCATION_ID),
                "inventory_item_id": inventory_item_id,
                "available": new_qty
            },
            headers={
                "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        
        return response.status_code in [200, 201]
        
    except Exception:
        return False


def read_csv_file(filename):
    """Read and parse CSV file"""
    rows = []
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                row['_row_num'] = i
                rows.append(row)
        
        return rows, None
        
    except FileNotFoundError:
        return None, f"File '{filename}' not found"
    except Exception as e:
        return None, f"Error reading file: {str(e)}"


def write_error_csv(filename, error_rows):
    """Write errors to CSV file"""
    if not error_rows:
        return
    
    fieldnames = list(error_rows[0]['original_row'].keys()) + ['error_reason']
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for error in error_rows:
            row_data = error['original_row'].copy()
            row_data['error_reason'] = '; '.join(error['errors'])
            writer.writerow(row_data)


def print_header():
    """Print script header"""
    print("\n" + "=" * 70)
    print("📦 DUMPLING COLLECTIBLES - Bulk Inventory Upload")
    print("=" * 70)
    print()


def main():
    """Main program"""
    print_header()
    
    # Check arguments
    if len(sys.argv) < 2:
        print("❌ Usage: python add_inventory_bulk.py filename.csv")
        print("\nExample: python add_inventory_bulk.py buylist_2025-11-25.csv")
        return
    
    filename = sys.argv[1]
    
    # Check database connection
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        return
    
    # Read CSV
    print(f"📂 Reading file: {filename}")
    rows, error = read_csv_file(filename)
    
    if error:
        print(f"❌ {error}")
        return
    
    print(f"✅ Found: {len(rows)} rows\n")
    
    # Validate all rows
    print("🔍 Validating data...")
    
    conn = psycopg2.connect(DATABASE_URL)
    
    valid_rows = []
    warning_rows = []
    error_rows = []
    
    for row in rows:
        row_num = row['_row_num']
        is_valid, warnings, errors, corrections = csv_validator.validate_row(row, row_num, conn)
        
        if is_valid:
            valid_rows.append({
                'row_num': row_num,
                'data': corrections,
                'warnings': warnings
            })
            if warnings:
                warning_rows.append({
                    'row_num': row_num,
                    'warnings': warnings
                })
        else:
            error_rows.append({
                'row_num': row_num,
                'errors': errors,
                'original_row': row
            })
    
    conn.close()
    
    # Show results
    print("\n" + "=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"\n✅ Valid: {len(valid_rows)} rows")
    print(f"⚠️  Warnings: {len(warning_rows)} rows")
    print(f"❌ Errors: {len(error_rows)} rows\n")
    
    # Show warnings
    if warning_rows:
        print("⚠️  WARNINGS (will proceed if confirmed):")
        for item in warning_rows[:5]:  # Show first 5
            print(f"Row {item['row_num']}:")
            for warning in item['warnings']:
                print(f"  • {warning}")
        if len(warning_rows) > 5:
            print(f"  ... and {len(warning_rows) - 5} more warnings")
        print()
    
    # Show errors
    if error_rows:
        print("❌ ERRORS (will be skipped):")
        for item in error_rows[:5]:  # Show first 5
            print(f"Row {item['row_num']}:")
            for error in item['errors']:
                print(f"  • {error}")
        if len(error_rows) > 5:
            print(f"  ... and {len(error_rows) - 5} more errors")
        print()
    
    print("=" * 70)
    print()
    
    # Export errors
    if error_rows:
        error_filename = f"errors_{os.path.basename(filename)}"
        write_error_csv(error_filename, error_rows)
        print(f"📄 Errors exported to: {error_filename}\n")
    
    # No valid rows
    if not valid_rows:
        print("❌ No valid rows to import.")
        return
    
    # Ask to proceed
    print("Options:")
    print(f"[1] Continue with {len(valid_rows)} valid rows (skip {len(error_rows)} errors)")
    print("[2] Cancel")
    
    choice = input("\nChoice (1-2): ").strip()
    
    if choice != '1':
        print("\n❌ Cancelled")
        return
    
    # Check for duplicates
    print("\n🔍 Checking for recent duplicates...")
    
    conn = psycopg2.connect(DATABASE_URL)
    duplicates_found = []
    
    for item in valid_rows:
        data = item['data']
        if 'card_id' in data and not data.get('needs_api_fetch'):
            is_dup, dup_info = csv_validator.check_recent_duplicate(
                data['card_id'],
                data['condition'],
                data['quantity'],
                data['unit_cost'],
                conn,
                hours=24
            )
            
            if is_dup:
                duplicates_found.append({
                    'row_num': item['row_num'],
                    'data': data,
                    'dup_info': dup_info
                })
    
    conn.close()
    
    if duplicates_found:
        print(f"\n⚠️  WARNING: {len(duplicates_found)} potential duplicate(s) found")
        print("\nRecent additions:")
        for dup in duplicates_found[:3]:
            hours_ago = (datetime.now() - dup['dup_info']['created_at']).seconds // 3600
            print(f"Row {dup['row_num']}: {dup['data']['original_row']['card_name']} ({dup['data']['condition']})")
            print(f"  Previous: {dup['dup_info']['quantity']} @ ${float(dup['dup_info']['unit_cost']):.2f} ({hours_ago}h ago)")
            print(f"  This row: {dup['data']['quantity']} @ ${dup['data']['unit_cost']:.2f}")
        
        if len(duplicates_found) > 3:
            print(f"  ... and {len(duplicates_found) - 3} more")
        
        proceed = input("\nProceed with duplicates? (y/n): ").strip().lower()
        if proceed != 'y':
            print("\n❌ Cancelled")
            return
    
    # Process rows
    print(f"\n⏳ Processing {len(valid_rows)} cards...\n")
    
    # Check for cards needing API fetch
    needs_fetch = [item for item in valid_rows if item['data'].get('needs_api_fetch')]
    
    if needs_fetch:
        print(f"⏳ {len(needs_fetch)} card(s) not in database - fetching from API...")
        
        for item in needs_fetch:
            data = item['data']
            row = data['original_row']
            
            print(f"  [{needs_fetch.index(item)+1}/{len(needs_fetch)}] Fetching {row['card_name']} ({row['set_code']}-{row['card_number']})...", end=' ')
            
            api_card = fetch_card_from_api(row['set_code'], row['card_number'])
            
            if api_card:
                market_price = extract_market_price(api_card)
                card_id = create_card_in_database(api_card, market_price)
                
                if card_id:
                    data['card_id'] = card_id
                    data['needs_api_fetch'] = False
                    print("✅")
                else:
                    print("❌ Failed to add to database")
                    item['skip'] = True
            else:
                print("❌ Not found in API")
                item['skip'] = True
            
            time.sleep(0.5)  # Rate limit
        
        print()
    
    # Add inventory
    print("⏳ Adding inventory...\n")
    
    success_count = 0
    shopify_sync_count = 0
    total_units = 0
    total_cost = 0
    total_value = 0
    transaction_ids = []
    
    for i, item in enumerate(valid_rows, 1):
        if item.get('skip'):
            continue
        
        data = item['data']
        row = data['original_row']
        
        # Get variant
        variant = get_variant_info(data['card_id'], data['condition'])
        
        if not variant:
            print(f"  [{i}/{len(valid_rows)}] ❌ Variant not found for row {item['row_num']}")
            continue
        
        # Calculate new values
        old_qty = variant['inventory_qty']
        old_wac = variant['cost_basis_avg']
        new_qty_add = data['quantity']
        new_qty_total = old_qty + new_qty_add
        new_wac = calculate_new_wac(old_qty, old_wac, new_qty_add, data['unit_cost'])
        total_units_purchased = (variant['total_units_purchased'] or 0) + new_qty_add
        
        # Update database
        if update_inventory(variant['variant_id'], new_qty_total, new_wac, total_units_purchased):
            # Log transaction
            notes = row.get('notes', '') or f"Bulk upload - Source: {data['source']}"
            transaction_id = log_transaction(
                variant['variant_id'],
                new_qty_add,
                data['unit_cost'],
                data['source'],
                notes
            )
            
            if transaction_id:
                transaction_ids.append(transaction_id)
            
            # Sync to Shopify
            if variant['shopify_variant_id']:
                if sync_to_shopify(variant['shopify_variant_id'], new_qty_total):
                    shopify_sync_count += 1
            
            success_count += 1
            total_units += new_qty_add
            total_cost += new_qty_add * data['unit_cost']
            total_value += new_qty_add * float(variant['price_cad'])
            
            if i % 10 == 0 or i == len(valid_rows):
                print(f"  Progress: {i}/{len(valid_rows)} ({success_count} successful)")
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ UPLOAD COMPLETE!")
    print("=" * 70)
    print(f"\nSummary:")
    print(f"• Cards processed: {success_count}")
    print(f"• Units added: {total_units} total")
    if needs_fetch:
        print(f"• New cards added to DB: {len([i for i in needs_fetch if not i.get('skip')])}")
    print(f"• Total value: ${total_value:.2f}")
    print(f"• Total cost: ${total_cost:.2f}")
    if total_cost > 0:
        print(f"• Potential profit: ${total_value - total_cost:.2f} ({((total_value - total_cost) / total_cost * 100):.1f}% margin)")
    print(f"• Synced to Shopify: {shopify_sync_count}")
    
    if transaction_ids:
        print(f"\nTransaction IDs: #{transaction_ids[0]}-#{transaction_ids[-1]}")
    
    if error_rows:
        print(f"\n📄 Errors saved to: errors_{os.path.basename(filename)}")
        print("   Fix errors and re-run with the error file")
    
    print("\n" + "=" * 70)
    print()


if __name__ == "__main__":
    main()
