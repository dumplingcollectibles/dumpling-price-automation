"""
IMPROVED Bulk Upload Script: High-value cards from 2020+ ($100+ CAD)

FIXES:
- Better retry logic for API timeouts
- Adds "Pokemon Singles" collection tag
- Better error handling
- Progress indicators
"""

import requests
import psycopg2
from psycopg2.extras import Json
import os
from dotenv import load_dotenv
import time
import math

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
USD_TO_CAD = 1.35
MARKUP = 1.10
MIN_PRICE_CAD = 25.00

# Modern sets - ALL sets from 2020 to present (swsh1 to me2)
MODERN_SETS = ['sv6', 'sv8']



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
            DO UPDATE SET external_ids = EXCLUDED.external_ids, img_url = EXCLUDED.img_url, updated_at = NOW()
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
            conn.rollback()
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
                    market_price = EXCLUDED.market_price, buy_cash = EXCLUDED.buy_cash,
                    buy_credit = EXCLUDED.buy_credit, price_cad = EXCLUDED.price_cad, updated_at = NOW()
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
            "tags": f"Pokemon Singles, {card_info['set_name']}, {card_info['rarity']}, Singles, High Value",  # ADDED "Pokemon Singles"
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
            
            # Set inventory to 0
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
            
            # Store Shopify IDs
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
    PAGINATION VERSION: Fetch ALL cards from a set (even sets with 300+ cards)
    Fetches 100 cards at a time and loops through all pages
    """
    all_cards = []
    page = 1
    page_size = 50  # Fetch 100 at a time for reliability
    
    print(f"   🔍 Fetching cards from {set_code}...")
    
    while True:
        url = f"{POKEMONTCG_API_URL}/cards"
        headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
        params = {
            "q": f"set.id:{set_code}", 
            "page": page,
            "pageSize": page_size
        }
        
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    wait_time = attempt * 5
                    print(f"      ⏳ Retry {attempt}/{max_retries} in {wait_time}s...")
                    time.sleep(wait_time)
                
                response = requests.get(url, headers=headers, params=params, timeout=90)
                
                if response.status_code == 200:
                    data = response.json()
                    cards = data.get('data', [])
                    total_count = data.get('totalCount', 0)
                    
                    if page == 1:
                        print(f"   📊 Set has {total_count} total cards")
                        if total_count > 250:
                            print(f"   ⚠️  IMPORTANT: This set has 250+ cards, using pagination to capture ALL cards!")
                    
                    if cards:
                        all_cards.extend(cards)
                        print(f"   ✅ Page {page}: Fetched {len(cards)} cards (Total so far: {len(all_cards)}/{total_count})")
                        
                        # Check if we've gotten all cards
                        if len(all_cards) >= total_count:
                            print(f"   🎉 Complete! Fetched all {len(all_cards)} cards from {set_code}")
                            return all_cards
                        
                        # Move to next page
                        page += 1
                        break  # Break retry loop, continue to next page
                    else:
                        # No more cards
                        if len(all_cards) > 0:
                            print(f"   ✅ Complete! Fetched {len(all_cards)} cards from {set_code}")
                            return all_cards
                        else:
                            print(f"   ⚠️  No cards found for {set_code}")
                            return []
                
                elif response.status_code == 404:
                    print(f"   ❌ Set '{set_code}' not found in API (404)")
                    return all_cards if all_cards else []
                else:
                    print(f"   ⚠️  API error {response.status_code} on page {page}, attempt {attempt}/{max_retries}")
                    if attempt >= max_retries:
                        print(f"   ⚠️  Failed to fetch page {page}, returning {len(all_cards)} cards fetched so far")
                        return all_cards
                        
            except requests.exceptions.Timeout:
                print(f"   ⏰ Timeout on page {page}, attempt {attempt}/{max_retries}")
                if attempt >= max_retries:
                    print(f"   ⚠️  Timeout on page {page}, returning {len(all_cards)} cards fetched so far")
                    return all_cards
            except Exception as e:
                print(f"   ❌ Error on page {page}: {str(e)[:100]}")
                if attempt >= max_retries:
                    return all_cards
        
        # Small delay between pages to be nice to the API
        time.sleep(1)
    
    return all_cards

def bulk_upload_high_value_cards():
    """Main function with improved error handling"""
    
    print("=" * 100)
    print("🚀 BULK UPLOAD: High-Value Pokemon Singles ($100+ CAD)")
    print("=" * 100)
    print(f"\nTarget: Cards worth ${MIN_PRICE_CAD:.2f}+ CAD from {len(MODERN_SETS)} modern sets")
    print(f"Collection: Pokemon Singles")
    print(f"Sets to process: {', '.join(MODERN_SETS)}\n")
    
    total_fetched = 0
    total_eligible = 0
    total_uploaded = 0
    total_skipped = 0
    failed_sets = []
    
    for i, set_code in enumerate(MODERN_SETS, 1):
        print(f"\n{'='*100}")
        print(f"[{i}/{len(MODERN_SETS)}] Processing Set: {set_code}")
        print('='*100)
        
        cards = fetch_cards_from_set(set_code)
        
        if not cards:
            print(f"   ⚠️  SKIPPING {set_code}: No cards fetched (API timeout or empty set)")
            failed_sets.append(set_code)
            continue
        
        total_fetched += len(cards)
        
        set_uploaded = 0
        set_eligible = 0
        
        for card in cards:
            market_usd = extract_market_price(card)
            if not market_usd:
                continue
            
            # Check if meets minimum price
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
                print(f"      ℹ️  Already exists, skipped")
                continue
            
            shopify_result = create_shopify_product(db_result)
            
            if shopify_result:
                total_uploaded += 1
                set_uploaded += 1
                print(f"      ✅ Uploaded to Shopify (Collection: Pokemon Singles)")
            
            time.sleep(0.5)  # Rate limiting
        
        print(f"\n   📊 Set Summary: Found {set_eligible} cards over ${MIN_PRICE_CAD:.2f}, uploaded {set_uploaded} new cards")
    
    print("\n" + "=" * 100)
    print("📊 BULK UPLOAD COMPLETE!")
    print("=" * 100)
    print(f"Total cards fetched:     {total_fetched}")
    print(f"Cards over ${MIN_PRICE_CAD:.2f}:      {total_eligible}")
    print(f"Successfully uploaded:   {total_uploaded}")
    print(f"Skipped (already exist): {total_skipped}")
    
    if failed_sets:
        print(f"\n⚠️  Failed/Skipped Sets ({len(failed_sets)}):")
        for s in failed_sets:
            print(f"   - {s}")
        print("\n💡 These sets likely timed out. You can:")
        print("   1. Run the script again (it will only process failed sets)")
        print("   2. Process them individually with lower card counts")
        print("   3. Wait 10-15 minutes and try again when API is less busy")
    
    print("=" * 100)

if __name__ == "__main__":
    bulk_upload_high_value_cards()
