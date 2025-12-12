"""
SCHEMA-CORRECTED Bulk Upload Script

FIXES:
- Uses ACTUAL database schema from your cards table
- Columns: name, set_name, set_code, number, variant, rarity, img_url, tcgplayer_id
- No card_id column (uses set_code + number for uniqueness)
- No api_data, set_id, supertype, subtypes columns
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

# Shopify Config (not used in this script but kept for compatibility)
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

# Modern sets - Default list
DEFAULT_MODERN_SETS = [
    'swsh8', 'swsh9', 'swsh10', 'swsh12','cel25c','swsh12tg',
    'swsh12pt5', 'pgo',
    'sv1', 'sv2', 'sv3', 'sv4', 'sv5', 'sv6', 'sv7', 'sv8', 'sv8pt5', 'sv9', 'sv10','rsv10pt5','zsv10pt5','me1','me2', 'svp', 
    'sv3pt5', 'sv4pt5', 'sv6pt5','fut20','swshp'
]

# Check if specific sets provided via environment variable
sets_input = os.getenv('SETS_TO_UPLOAD', '').strip()
if sets_input:
    MODERN_SETS = [s.strip() for s in sets_input.split(',') if s.strip()]
    print(f"📌 Using provided sets: {', '.join(MODERN_SETS)}")
else:
    MODERN_SETS = DEFAULT_MODERN_SETS
    print(f"📌 Using default set list ({len(MODERN_SETS)} sets)")

# Check for minimum price override
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


def fetch_cards_from_api(set_code, max_retries=3):
    """Fetch all cards from Pokemon TCG API for a given set with retry logic"""
    headers = {"X-Api-Key": TCG_API_KEY} if TCG_API_KEY else {}
    all_cards = []
    page = 1
    total_cards = None
    
    while True:
        retry_count = 0
        success = False
        
        # Retry logic for each page
        while retry_count < max_retries and not success:
            try:
                url = f"{POKEMONTCG_API_URL}/cards?q=set.id:{set_code}&page={page}&pageSize=250"
                
                # Debug output on first page
                if page == 1:
                    print(f"   🔗 API URL: {url}")
                    print(f"   🔑 Has API Key: {'Yes' if TCG_API_KEY else 'No'}")
                
                # Increased timeout: 60 seconds
                response = requests.get(url, headers=headers, timeout=60)
                
                if response.status_code != 200:
                    print(f"   ⚠️  API returned status {response.status_code}")
                    print(f"   📄 Response body: {response.text[:500]}")
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"   🔄 Retrying... (attempt {retry_count + 1}/{max_retries})")
                        time.sleep(2 ** retry_count)  # Exponential backoff: 2s, 4s, 8s
                    continue
                
                data = response.json()
                cards = data.get('data', [])
                
                if not cards:
                    # No more cards, exit successfully
                    return all_cards
                
                all_cards.extend(cards)
                success = True
                
                if total_cards is None:
                    total_cards = data.get('totalCount', len(cards))
                    print(f"   📊 Total cards in set: {total_cards}")
                else:
                    # Show progress
                    print(f"   📥 Fetched {len(all_cards)}/{total_cards} cards (page {page})")
                
                if len(all_cards) >= total_cards:
                    return all_cards
                
                page += 1
                time.sleep(0.5)  # Rate limiting delay
                
            except requests.exceptions.Timeout:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"   ⏱️  Timeout on page {page}, retrying... (attempt {retry_count + 1}/{max_retries})")
                    time.sleep(2 ** retry_count)  # Exponential backoff
                else:
                    print(f"   ❌ Failed after {max_retries} timeout attempts on page {page}")
                    return all_cards
                    
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"   ⚠️  Error on page {page}: {str(e)[:100]}")
                    print(f"   🔄 Retrying... (attempt {retry_count + 1}/{max_retries})")
                    time.sleep(2 ** retry_count)
                else:
                    print(f"   ❌ Failed after {max_retries} attempts: {str(e)[:100]}")
                    return all_cards
        
        if not success:
            # Failed all retries for this page
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


def card_exists_in_db(set_code, number):
    """Check if card already exists in database using set_code + number"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id FROM cards WHERE set_code = %s AND number = %s", 
        (set_code, number)
    )
    result = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return result is not None


def insert_card_to_db(api_card, market_price_cad, selling_price_cad):
    """Insert card and its variants into database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        # Extract values from API card
        set_code = api_card.get('set', {}).get('id')
        set_name = api_card.get('set', {}).get('name')
        number = api_card.get('number')
        name = api_card.get('name')
        rarity = api_card.get('rarity')
        
        # Get image URL (prefer large, fallback to small)
        images = api_card.get('images', {})
        img_url = images.get('large') or images.get('small')
        
        # Get tcgplayer_id if available
        tcgplayer = api_card.get('tcgplayer', {})
        tcgplayer_id = tcgplayer.get('productId')
        
        # Variant is empty for base cards (could be "Holo", "Reverse Holo", etc.)
        variant = None
        
        # Insert card - MATCHES YOUR ACTUAL SCHEMA
        cursor.execute("""
            INSERT INTO cards (name, set_name, set_code, number, variant, rarity, 
                              img_url, tcgplayer_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (
            name,
            set_name,
            set_code,
            number,
            variant,
            rarity,
            img_url,
            tcgplayer_id
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
        print(f"      ❌ DB error for {api_card.get('name', 'unknown')}: {str(e)[:200]}")
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
        print(f"   ❌ FAILED: No cards retrieved from API for set '{set_code}'")
        print(f"   💡 This could be due to:")
        print(f"      • Network timeout (GitHub Actions network issue)")
        print(f"      • Invalid set code")
        print(f"      • API rate limiting")
        print(f"   🔄 Set marked as FAILED - will retry on next run")
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
        set_code_val = api_card.get('set', {}).get('id')
        number = api_card.get('number')
        
        if card_exists_in_db(set_code_val, number):
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
