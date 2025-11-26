"""
CORRECTED Bulk Upload Script - Properly Handles Retries

FIX:
- Sets with 0 eligible cards are now marked as FAILED (not completed)
- This allows retry in case API didn't return all cards
- Progress tracking fixed to remove failed sets when they succeed
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


def transform_card_data(api_card, market_price_usd):
    if market_price_usd:
        base_market_cad = market_price_usd * USD_TO_CAD
        nm_selling_price = round_up_to_nearest_50_cents(base_market_cad * MARKUP)
    else:
        base_market_cad = 50.00
        nm_selling_price = 57.50
    
    return {
        'external_ids': {'pokemontcg_io': api_card['id']},
        'name': api_card['name'],
        'set_code': api_card['set']['id'],
        'set_name': api_card['set']['name'],
        'number': api_card['number'],
        'variant': 'Normal',
        'language': 'English',
        'rarity': api_card.get('rarity', 'Unknown'),
        'supertype': api_card.get('supertype', 'Unknown'),
        'img_url': api_card['images']['large'],
        'release_date': api_card['set']['releaseDate'],
        'base_market_cad': base_market_cad,
        'nm_selling_price': nm_selling_price
    }


def calculate_buylist_prices(market_price, condition, nm_buy_cash=None, nm_buy_credit=None):
    if condition in ['HP', 'DMG']:
        return None, None
    
    if condition == 'NM':
        if market_price < 50:
            cash_pct, credit_pct = 0.60, 0.70
        elif market_price < 100:
            cash_pct, credit_pct = 0.70, 0.80
        else:
            cash_pct, credit_pct = 0.75, 0.85
        return int((market_price * cash_pct) * 2) / 2, int((market_price * credit_pct) * 2) / 2
    elif condition == 'LP':
        return round(nm_buy_cash * 0.75, 2), round(nm_buy_credit * 0.75, 2)
    elif condition == 'MP':
        return round(nm_buy_cash * 0.50, 2), round(nm_buy_credit * 0.50, 2)
    return None, None


def insert_card_to_database(card_info):
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO cards (
                external_ids, name, set_code, set_name, number, 
                variant, language, rarity, supertype, img_url, release_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name, set_code, number, variant, language) 
            DO UPDATE SET 
                external_ids = EXCLUDED.external_ids, 
                img_url = EXCLUDED.img_url, 
                updated_at = NOW()
            RETURNING id;
        """, (
            Json(card_info['external_ids']), card_info['name'], card_info['set_code'],
            card_info['set_name'], card_info['number'], card_info['variant'],
            card_info['language'], card_info['rarity'], card_info['supertype'],
            card_info['img_url'], card_info['release_date']
        ))
        card_id = cursor.fetchone()[0]
        
        cursor.execute("SELECT id, shopify_product_id FROM products WHERE card_id = %s", (card_id,))
        existing = cursor.fetchone()
        
        if existing and existing[1]:
            conn.commit()
            cursor.close()
            conn.close()
            return None
        
        if not existing:
            handle = f"{card_info['name']}-{card_info['set_code']}-{card_info['number']}".lower()
            handle = handle.replace(' ', '-').replace("'", '').replace('!', '').replace('.', '')
            cursor.execute("""
                INSERT INTO products (card_id, handle, product_type, status, tags)
                VALUES (%s, %s, %s, %s, %s) RETURNING id;
            """, (card_id, handle, 'Single', 'draft', [card_info['set_name'], card_info['name'], card_info['rarity']]))
            product_id = cursor.fetchone()[0]
        else:
            product_id = existing[0]
        
        base_market = card_info['base_market_cad']
        nm_price = card_info['nm_selling_price']
        conditions = ['NM', 'LP', 'MP', 'HP', 'DMG']
        condition_selling_multipliers = {'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35}
        
        nm_buy_cash, nm_buy_credit = calculate_buylist_prices(base_market, 'NM')
        variant_ids = []
        
        for condition in conditions:
            sku = f"{card_info['set_code'].upper()}-{card_info['number']}-{condition}"
            selling_price = nm_price if condition == 'NM' else round(nm_price * condition_selling_multipliers[condition], 2)
            
            if condition in ['NM', 'LP', 'MP']:
                buy_cash, buy_credit = calculate_buylist_prices(base_market, condition, nm_buy_cash, nm_buy_credit)
            else:
                buy_cash, buy_credit = None, None
            
            cursor.execute("""
                INSERT INTO variants (product_id, condition, sku, inventory_qty, market_price, buy_cash, buy_credit, price_cad)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sku) DO UPDATE SET
                    market_price = EXCLUDED.market_price, 
                    buy_cash = EXCLUDED.buy_cash,
                    buy_credit = EXCLUDED.buy_credit, 
                    price_cad = EXCLUDED.price_cad, 
                    updated_at = NOW()
                RETURNING id;
            """, (product_id, condition, sku, 0, base_market, buy_cash, buy_credit, selling_price))
            
            variant_id = cursor.fetchone()[0]
            variant_ids.append({'id': variant_id, 'condition': condition, 'sku': sku, 'price': selling_price})
        
        conn.commit()
        return {'card_id': card_id, 'product_id': product_id, 'variant_ids': variant_ids, 'card_info': card_info}
    
    except Exception as e:
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()


def create_shopify_product(db_result):
    if not SHOPIFY_ACCESS_TOKEN:
        return None
    
    card_info = db_result['card_info']
    product_data = {
        "product": {
            "title": f"{card_info['name']} - {card_info['set_name']} #{card_info['number']}",
            "body_html": f"<p>Set: {card_info['set_name']}<br>Card Number: {card_info['number']}<br>Rarity: {card_info['rarity']}</p>",
            "vendor": "Pokemon",
            "product_type": "Trading Card - Single",
            "tags": f"Pokemon Singles, {card_info['set_name']}, {card_info['rarity']}, Singles",
            "status": "active",
            "images": [{"src": card_info['img_url']}],
            "options": [{"name": "Condition"}],
            "variants": [{"option1": v['condition'], "price": str(v['price']), "sku": v['sku'], 
                         "inventory_management": "shopify", "inventory_policy": "deny"} 
                        for v in db_result['variant_ids']]
        }
    }
    
    try:
        response = requests.post(
            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/products.json",
            json=product_data,
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 201:
            shopify_product = response.json()['product']
            
            if SHOPIFY_LOCATION_ID:
                for variant in shopify_product['variants']:
                    try:
                        requests.post(
                            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels/set.json",
                            json={"location_id": int(SHOPIFY_LOCATION_ID), "inventory_item_id": variant['inventory_item_id'], "available": 0},
                            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN},
                            timeout=10
                        )
                    except:
                        pass
            
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE products SET shopify_product_id = %s, status = 'active', published_at = NOW(), updated_at = NOW() WHERE id = %s",
                              (str(shopify_product['id']), db_result['product_id']))
                for db_v, shop_v in zip(db_result['variant_ids'], shopify_product['variants']):
                    cursor.execute("UPDATE variants SET shopify_variant_id = %s, updated_at = NOW() WHERE id = %s",
                                  (str(shop_v['id']), db_v['id']))
                conn.commit()
            except:
                conn.rollback()
            finally:
                cursor.close()
                conn.close()
            
            return shopify_product
    except:
        pass
    
    return None


def fetch_cards_from_set(set_code, max_retries=5):
    """
    Fetch with smaller page size (50) and longer waits for better reliability
    """
    all_cards = []
    page = 1
    page_size = 50
    
    print(f"   🔍 Fetching cards from {set_code}...")
    
    while True:
        url = f"{POKEMONTCG_API_URL}/cards"
        headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
        params = {
            "q": f"set.id:{set_code}", 
            "page": page,
            "pageSize": page_size
        }
        
        success = False
        
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    wait_time = attempt * 10
                    print(f"      ⏳ Retry {attempt}/{max_retries} (page {page}) in {wait_time}s...")
                    time.sleep(wait_time)
                
                response = requests.get(url, headers=headers, params=params, timeout=90)
                
                if response.status_code == 200:
                    data = response.json()
                    cards = data.get('data', [])
                    total_count = data.get('totalCount', 0)
                    
                    if page == 1:
                        print(f"   📊 Set has {total_count} total cards")
                    
                    if cards:
                        all_cards.extend(cards)
                        print(f"   ✅ Page {page}: Fetched {len(cards)} cards (Total: {len(all_cards)}/{total_count})")
                        
                        if len(all_cards) >= total_count:
                            print(f"   🎉 Complete! Fetched all {len(all_cards)} cards")
                            return all_cards
                        
                        page += 1
                        success = True
                        break
                    else:
                        if len(all_cards) > 0:
                            print(f"   ✅ Complete! Fetched {len(all_cards)} cards")
                            return all_cards
                        else:
                            if page == 1:
                                print(f"   ⚠️  No cards found in {set_code}")
                            return []
                
                elif response.status_code == 404:
                    if page == 1:
                        if attempt >= max_retries:
                            print(f"   ❌ Set '{set_code}' not found (404 after {max_retries} retries)")
                            return []
                        print(f"   ⚠️  404 on page 1, attempt {attempt}/{max_retries} (might be API hiccup)")
                        continue
                    else:
                        if attempt >= max_retries:
                            print(f"   ✅ Assuming end of data. Fetched {len(all_cards)} cards total")
                            return all_cards
                        continue
                
                else:
                    if attempt >= max_retries:
                        if len(all_cards) > 0:
                            print(f"   ⚠️  Returning {len(all_cards)} cards fetched so far")
                            return all_cards
                        else:
                            return []
                        
            except requests.exceptions.Timeout:
                if attempt >= max_retries:
                    if len(all_cards) > 0:
                        print(f"   ⚠️  Timeout - returning {len(all_cards)} cards fetched so far")
                        return all_cards
                    else:
                        return []
            
            except Exception as e:
                if attempt >= max_retries:
                    return all_cards
        
        if not success:
            if len(all_cards) > 0:
                print(f"   ⚠️  Failed page {page}. Returning {len(all_cards)} cards")
                return all_cards
            else:
                return []
        
        time.sleep(3)
    
    return all_cards


def bulk_upload_high_value_cards():
    progress = load_progress()
    completed = set(progress["completed_sets"])
    failed = set(progress["failed_sets"])
    
    remaining_sets = [s for s in MODERN_SETS if s not in completed]
    
    print("=" * 100)
    print("🚀 BULK UPLOAD: Pokemon Singles ($25+ CAD) - WITH RESUME")
    print("=" * 100)
    
    if progress["last_run"]:
        print(f"\n📂 Previous run: {progress['last_run']}")
        print(f"   ✅ Completed: {len(completed)} sets")
        print(f"   ❌ Failed: {len(failed)} sets")
        print(f"   ⏳ Remaining: {len(remaining_sets)} sets")
    
    print(f"\n💡 TIP: For best results, run between 11pm-6am when API is faster!")
    print(f"Target: ${MIN_PRICE_CAD:.2f}+ CAD cards\n")
    
    total_fetched = 0
    total_eligible = 0
    total_uploaded = 0
    total_skipped = 0
    new_failed = []
    new_completed = []
    
    for i, set_code in enumerate(remaining_sets, 1):
        print(f"\n{'='*100}")
        print(f"[{i}/{len(remaining_sets)}] Processing: {set_code}")
        print('='*100)
        
        cards = fetch_cards_from_set(set_code)
        
        if not cards:
            print(f"   ⚠️  SKIPPING {set_code}: No cards fetched (API issue)")
            new_failed.append(set_code)
            all_completed = completed | set(new_completed)
            all_failed = (failed | set(new_failed)) - all_completed
            save_progress(list(all_completed), list(all_failed))
            continue
        
        total_fetched += len(cards)
        set_uploaded = 0
        set_eligible = 0
        
        for card in cards:
            market_usd = extract_market_price(card)
            if not market_usd:
                continue
            
            base_cad = market_usd * USD_TO_CAD
            nm_price = round_up_to_nearest_50_cents(base_cad * MARKUP)
            
            if nm_price < MIN_PRICE_CAD:
                continue
            
            set_eligible += 1
            total_eligible += 1
            
            print(f"\n   💎 {card['name']} #{card['number']} - ${nm_price:.2f} CAD")
            
            card_info = transform_card_data(card, market_usd)
            db_result = insert_card_to_database(card_info)
            
            if not db_result:
                total_skipped += 1
                continue
            
            shopify_result = create_shopify_product(db_result)
            
            if shopify_result:
                total_uploaded += 1
                set_uploaded += 1
                print(f"      ✅ Uploaded")
            
            time.sleep(0.5)
        
        # FIXED LOGIC: Only mark as completed if we found eligible cards
        if set_eligible > 0:
            # Success - found cards to upload
            new_completed.append(set_code)
            print(f"\n   ✅ Set completed: {set_eligible} eligible, {set_uploaded} uploaded")
        else:
            # No eligible cards - might be incomplete API data, mark as failed to retry
            print(f"\n   ⚠️  No cards over ${MIN_PRICE_CAD:.2f} found - marking for retry")
            new_failed.append(set_code)
        
        # Save progress with proper cleanup
        all_completed = completed | set(new_completed)
        all_failed = (failed | set(new_failed)) - all_completed  # Remove completed from failed
        save_progress(list(all_completed), list(all_failed))
    
    print("\n" + "=" * 100)
    print("📊 COMPLETE!")
    print("=" * 100)
    print(f"Total fetched:       {total_fetched}")
    print(f"Over ${MIN_PRICE_CAD:.2f}:          {total_eligible}")
    print(f"Uploaded:            {total_uploaded}")
    print(f"Skipped:             {total_skipped}")
    print(f"Failed sets:         {len(new_failed)}")
    
    if new_failed:
        print(f"\n⚠️  Failed: {', '.join(new_failed)}")
        print("\n💡 These sets will be retried on next run!")
    
    print("=" * 100)


if __name__ == "__main__":
    bulk_upload_high_value_cards()
