"""
CORRECTED Bulk Upload Script - Standalone Version (No Dependencies)

FIXES:
- Removed csv_validator dependency (not needed for this script)
- Sets with 0 eligible cards are marked as FAILED (allows retry)
- Progress tracking fixed to remove failed sets when they succeed
- Works in GitHub Actions without external modules

This script does NOT use CSV validation - it directly fetches cards from Pokemon TCG API
"""

import requests
import psycopg2
from psycopg2.extras import Json
import os
from dotenv import load_dotenv
import time
import math
import json
from datetime import datetime

load_dotenv()

# Database & API Config
DATABASE_URL = os.getenv('NEON_DB_URL')
POKEMONTCG_API_URL = os.getenv('POKEMONTCG_API_URL', 'https://api.pokemontcg.io/v2')
TCG_API_KEY = os.getenv('TCG_API_KEY')

# Shopify Config
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"

# Pricing Config
USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))
MARKUP = float(os.getenv('MARKUP', '1.10'))
MIN_PRICE_CAD = float(os.getenv('MIN_PRICE_CAD', '25.00'))

# Progress tracking file
PROGRESS_FILE = "bulk_upload_progress.json"

# Modern sets - Default list (all modern sets 2020-2025)
DEFAULT_MODERN_SETS = [
    'swsh8', 'swsh9', 'swsh10', 'swsh12','cel25c','swsh12tg',
    'swsh12pt5', 'pgo',
    'sv1', 'sv2', 'sv3', 'sv4', 'sv5', 'sv6', 'sv7', 'sv8', 'sv8pt5', 'sv9', 'sv10','rsv10pt5','zsv10pt5','me1','me2', 'svp', 
    'sv3pt5', 'sv4pt5', 'sv6pt5','fut20','swshp'
]

# Check if specific sets provided via environment variable (from GitHub Actions input)
sets_input = os.getenv('SETS_TO_UPLOAD', '').strip()
if sets_input:
    # Split by comma and clean up whitespace
    MODERN_SETS = [s.strip() for s in sets_input.split(',') if s.strip()]
    print(f"📌 Using provided sets: {', '.join(MODERN_SETS)}")
else:
    MODERN_SETS = DEFAULT_MODERN_SETS
    print(f"📌 Using default set list ({len(MODERN_SETS)} sets)")

# Check for minimum price override from GitHub Actions input
min_price_input = os.getenv('MIN_PRICE_OVERRIDE', '').strip()
if min_price_input:
    try:
        MIN_PRICE_CAD = float(min_price_input)
        print(f"💰 Using minimum price override: ${MIN_PRICE_CAD:.2f} CAD")
    except ValueError:
        print(f"⚠️  Invalid MIN_PRICE_OVERRIDE value '{min_price_input}', using default: ${MIN_PRICE_CAD:.2f}")


def load_progress():
    """Load completed sets from previous runs"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {"completed_sets": [], "failed_sets": [], "last_run": None}
    return {"completed_sets": [], "failed_sets": [], "last_run": None}


def save_progress(completed_sets, failed_sets):
    """Save progress after each set"""
    progress = {
        "completed_sets": completed_sets,
        "failed_sets": failed_sets,
        "last_run": datetime.now().isoformat()
    }
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def round_up_to_nearest_50_cents(amount):
    return math.ceil(amount * 2) / 2


def extract_market_price(api_card):
    tcgplayer = api_card.get('tcgplayer', {})
    prices = tcgplayer.get('prices', {})
    for price_type in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil']:
        if price_type in prices:
            price_data = prices[price_type]
            market = price_data.get('market') or price_data.get('mid') or price_data.get('low')
            if market and market > 0:
                return float(market)
    return None


def calculate_buylist_prices(market_price_cad, condition, nm_buy_cash=None, nm_buy_credit=None):
    """Calculate buylist prices based on market price and condition"""
    
    if market_price_cad < 50:
        cash_percent = 0.60
        credit_percent = 0.70
    elif market_price_cad < 100:
        cash_percent = 0.70
        credit_percent = 0.80
    else:
        cash_percent = 0.75
        credit_percent = 0.85
    
    if condition == 'NM':
        buy_cash = round_up_to_nearest_50_cents(market_price_cad * cash_percent)
        buy_credit = round_up_to_nearest_50_cents(market_price_cad * credit_percent)
        return buy_cash, buy_credit
    elif condition == 'LP':
        buy_cash = round_up_to_nearest_50_cents(nm_buy_cash * 0.80) if nm_buy_cash else None
        buy_credit = round_up_to_nearest_50_cents(nm_buy_credit * 0.80) if nm_buy_credit else None
        return buy_cash, buy_credit
    elif condition == 'MP':
        buy_cash = round_up_to_nearest_50_cents(nm_buy_cash * 0.65) if nm_buy_cash else None
        buy_credit = round_up_to_nearest_50_cents(nm_buy_credit * 0.65) if nm_buy_credit else None
        return buy_cash, buy_credit
    else:
        return None, None


def fetch_cards_from_api(set_code):
    """Fetch all cards from Pokemon TCG API for a given set"""
    headers = {"X-Api-Key": TCG_API_KEY} if TCG_API_KEY else {}
    all_cards = []
    page = 1
    total_cards = None
    
    while True:
        try:
            url = f"{POKEMONTCG_API_URL}/cards?q=set.id:{set_code}&page={page}&pageSize=250"
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"   ⚠️  API returned status {response.status_code}")
                break
            
            data = response.json()
            cards = data.get('data', [])
            
            if not cards:
                break
            
            all_cards.extend(cards)
            
            if total_cards is None:
                total_cards = data.get('totalCount', len(cards))
            
            if len(all_cards) >= total_cards:
                break
            
            page += 1
            time.sleep(0.3)  # Rate limiting
            
        except Exception as e:
            print(f"   ❌ API error: {str(e)[:100]}")
            break
    
    return all_cards


def filter_eligible_cards(api_cards, min_price_cad):
    """Filter cards that meet price requirements"""
    eligible = []
    
    for card in api_cards:
        market_price_usd = extract_market_price(card)
        
        if not market_price_usd:
            continue
        
        market_price_cad = market_price_usd * USD_TO_CAD
        selling_price_cad = round_up_to_nearest_50_cents(market_price_cad * MARKUP)
        
        if selling_price_cad >= min_price_cad:
            eligible.append({
                'api_card': card,
                'market_price_usd': market_price_usd,
                'market_price_cad': market_price_cad,
                'selling_price_cad': selling_price_cad
            })
    
    return eligible


def card_exists_in_db(card_id):
    """Check if card already exists in database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM cards WHERE card_id = %s", (card_id,))
    result = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return result is not None


def insert_card_to_db(api_card, market_price_cad, selling_price_cad):
    """Insert card and its variants into database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        # Insert card
        cursor.execute("""
            INSERT INTO cards (card_id, name, set_id, set_name, number, rarity, 
                              supertype, subtypes, image_url, api_data, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (
            api_card['id'],
            api_card.get('name'),
            api_card.get('set', {}).get('id'),
            api_card.get('set', {}).get('name'),
            api_card.get('number'),
            api_card.get('rarity'),
            api_card.get('supertype'),
            Json(api_card.get('subtypes', [])),
            api_card.get('images', {}).get('large') or api_card.get('images', {}).get('small'),
            Json(api_card)
        ))
        
        card_db_id = cursor.fetchone()[0]
        
        # Insert product
        cursor.execute("""
            INSERT INTO products (card_id, created_at, updated_at)
            VALUES (%s, NOW(), NOW())
            RETURNING id
        """, (card_db_id,))
        
        product_id = cursor.fetchone()[0]
        
        # Calculate buylist prices
        nm_buy_cash, nm_buy_credit = calculate_buylist_prices(market_price_cad, 'NM')
        lp_buy_cash, lp_buy_credit = calculate_buylist_prices(market_price_cad, 'LP', nm_buy_cash, nm_buy_credit)
        mp_buy_cash, mp_buy_credit = calculate_buylist_prices(market_price_cad, 'MP', nm_buy_cash, nm_buy_credit)
        
        # Insert variants
        conditions = {
            'NM': (1.00, nm_buy_cash, nm_buy_credit),
            'LP': (0.80, lp_buy_cash, lp_buy_credit),
            'MP': (0.65, mp_buy_cash, mp_buy_credit),
            'HP': (0.50, None, None),
            'DMG': (0.35, None, None)
        }
        
        for condition, (multiplier, buy_cash, buy_credit) in conditions.items():
            price_cad = round(selling_price_cad * multiplier, 2)
            
            cursor.execute("""
                INSERT INTO variants (product_id, condition, market_price, price_cad, 
                                     buy_cash, buy_credit, inventory_qty, 
                                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 0, NOW(), NOW())
            """, (product_id, condition, market_price_cad, price_cad, buy_cash, buy_credit))
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"      ❌ DB error: {str(e)[:200]}")
        return False
    finally:
        cursor.close()
        conn.close()


def process_set(set_code, min_price_cad):
    """Process a single set"""
    print(f"\n{'='*70}")
    print(f"📦 Processing Set: {set_code}")
    print(f"{'='*70}")
    
    # Fetch cards from API
    print(f"   🔍 Fetching cards from Pokemon TCG API...")
    api_cards = fetch_cards_from_api(set_code)
    
    if not api_cards:
        print(f"   ⚠️  No cards found in API for set '{set_code}'")
        return False, 0, 0  # Failed
    
    print(f"   ✅ Found {len(api_cards)} cards in API")
    
    # Filter eligible cards
    print(f"   💰 Filtering cards >= ${min_price_cad:.2f} CAD...")
    eligible_cards = filter_eligible_cards(api_cards, min_price_cad)
    
    if not eligible_cards:
        print(f"   ⚠️  No cards meet minimum price requirement (${min_price_cad:.2f} CAD)")
        return False, len(api_cards), 0  # Failed - no eligible cards
    
    print(f"   ✅ Found {len(eligible_cards)} eligible cards")
    
    # Process each card
    print(f"   📝 Inserting cards into database...")
    
    new_cards = 0
    existing_cards = 0
    
    for idx, card_data in enumerate(eligible_cards, 1):
        api_card = card_data['api_card']
        card_id = api_card['id']
        
        if card_exists_in_db(card_id):
            existing_cards += 1
            continue
        
        if insert_card_to_db(
            api_card,
            card_data['market_price_cad'],
            card_data['selling_price_cad']
        ):
            new_cards += 1
        
        if idx % 10 == 0:
            print(f"      Progress: {idx}/{len(eligible_cards)} cards processed")
        
        time.sleep(0.1)  # Small delay
    
    print(f"\n   ✅ Set '{set_code}' complete!")
    print(f"      New cards added: {new_cards}")
    print(f"      Already existed: {existing_cards}")
    
    return True, len(api_cards), new_cards


def main():
    """Main execution"""
    print("\n" + "="*70)
    print("🚀 BULK PRODUCT UPLOAD - Pokemon TCG")
    print("="*70)
    print(f"Minimum Price: ${MIN_PRICE_CAD:.2f} CAD")
    print(f"Sets to process: {len(MODERN_SETS)}")
    print("="*70)
    
    # Load progress
    progress = load_progress()
    completed_sets = set(progress.get('completed_sets', []))
    failed_sets = set(progress.get('failed_sets', []))
    
    if completed_sets:
        print(f"\n✅ Already completed: {len(completed_sets)} sets")
    if failed_sets:
        print(f"⚠️  Previously failed: {len(failed_sets)} sets (will retry)")
    
    # Filter sets to process
    sets_to_process = [s for s in MODERN_SETS if s not in completed_sets]
    
    if not sets_to_process:
        print("\n🎉 All sets already completed!")
        return
    
    print(f"\n📋 Will process: {len(sets_to_process)} sets")
    print("="*70)
    
    # Process each set
    total_cards_found = 0
    total_cards_added = 0
    successful_sets = []
    new_failed_sets = []
    
    for idx, set_code in enumerate(sets_to_process, 1):
        print(f"\n[{idx}/{len(sets_to_process)}]", end=" ")
        
        success, cards_found, cards_added = process_set(set_code, MIN_PRICE_CAD)
        
        total_cards_found += cards_found
        total_cards_added += cards_added
        
        if success:
            completed_sets.add(set_code)
            successful_sets.append(set_code)
            # Remove from failed if it was there
            failed_sets.discard(set_code)
        else:
            new_failed_sets.append(set_code)
            failed_sets.add(set_code)
        
        # Save progress after each set
        save_progress(list(completed_sets), list(failed_sets))
        
        time.sleep(1)  # Rate limiting between sets
    
    # Final summary
    print("\n" + "="*70)
    print("🎉 UPLOAD COMPLETE!")
    print("="*70)
    print(f"\n📊 Summary:")
    print(f"   Sets processed: {len(sets_to_process)}")
    print(f"   ✅ Successful: {len(successful_sets)}")
    print(f"   ❌ Failed: {len(new_failed_sets)}")
    print(f"   📦 Total cards found: {total_cards_found}")
    print(f"   ➕ Total cards added: {total_cards_added}")
    
    if new_failed_sets:
        print(f"\n⚠️  Failed sets (will retry next run):")
        for set_code in new_failed_sets:
            print(f"      • {set_code}")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
