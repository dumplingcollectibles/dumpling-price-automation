"""
Daily Price Tracker
Dumpling Collectibles

Tracks market prices for cards with inventory > 0
Runs daily at 2 AM EST (silent, no notifications)

Usage:
    python daily_price_tracker.py
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import math
import time

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
POKEMONTCG_API_URL = os.getenv('POKEMONTCG_API_URL', 'https://api.pokemontcg.io/v2')
TCG_API_KEY = os.getenv('TCG_API_KEY')
USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))
MARKUP = float(os.getenv('MARKUP', '1.10'))

# API rate limiting
API_DELAY = 0.1  # 100ms delay between requests (avoid rate limits)


def round_up_to_nearest_50_cents(amount):
    """Round up to nearest $0.50"""
    return math.ceil(amount * 2) / 2


def fetch_current_market_price(pokemontcg_id):
    """
    Fetch current market price from PokemonTCG.io API
    Returns: market_price_usd (float) or None
    """
    if not pokemontcg_id:
        return None
    
    url = f"{POKEMONTCG_API_URL}/cards/{pokemontcg_id}"
    headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            card = data.get('data', {})
            
            # Extract market price
            tcgplayer = card.get('tcgplayer', {})
            prices = tcgplayer.get('prices', {})
            
            # Try different price types
            for price_type in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil', '1stEditionHolofoil']:
                if price_type in prices:
                    price_data = prices[price_type]
                    market = price_data.get('market') or price_data.get('mid') or price_data.get('low')
                    if market and market > 0:
                        return float(market)
        
        return None
        
    except Exception as e:
        # Silent failure - log but continue
        print(f"  ⚠️  API error for {pokemontcg_id}: {str(e)[:50]}")
        return None


def get_cards_with_inventory():
    """
    Get all cards that have inventory > 0
    Returns: list of dicts with card info
    """
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                c.id as card_id,
                c.name as card_name,
                c.set_code,
                c.number,
                c.external_ids,
                v.id as variant_id,
                v.condition,
                v.inventory_qty
            FROM cards c
            JOIN products p ON p.card_id = c.id
            JOIN variants v ON v.product_id = p.id
            WHERE v.inventory_qty > 0
            AND c.language = 'English'
            ORDER BY c.set_code, c.number, v.condition
        """)
        
        cards = cursor.fetchall()
        return cards
        
    finally:
        cursor.close()
        conn.close()


def store_price(card_id, condition, market_price_usd, market_price_cad, suggested_price_cad):
    """
    Store price in price_history table
    Returns: True if successful, False otherwise
    """
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO price_history (
                card_id,
                condition,
                market_price_usd,
                market_price_cad,
                suggested_price_cad,
                source,
                checked_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (card_id, condition, DATE(NOW())) 
            DO UPDATE SET
                market_price_usd = EXCLUDED.market_price_usd,
                market_price_cad = EXCLUDED.market_price_cad,
                suggested_price_cad = EXCLUDED.suggested_price_cad,
                checked_at = NOW()
        """, (
            card_id,
            condition,
            market_price_usd,
            market_price_cad,
            suggested_price_cad,
            'pokemontcg_io'
        ))
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Database error: {str(e)[:50]}")
        return False
        
    finally:
        cursor.close()
        conn.close()


def track_prices():
    """
    Main function: Track prices for all cards with inventory
    """
    print("="*70)
    print("📊 DAILY PRICE TRACKER")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print()
    
    # Get cards with inventory
    print("📦 Fetching cards with inventory...")
    cards = get_cards_with_inventory()
    print(f"✅ Found {len(cards)} card variants with inventory > 0")
    print()
    
    if not cards:
        print("ℹ️  No cards in inventory. Nothing to track.")
        return {
            'total_cards': 0,
            'tracked': 0,
            'skipped': 0,
            'errors': 0
        }
    
    # Track prices
    print(f"🔍 Tracking prices for {len(cards)} variants...")
    print()
    
    tracked = 0
    skipped_no_id = 0
    skipped_no_price = 0
    errors = 0
    
    for i, card in enumerate(cards, 1):
        # Progress indicator
        if i % 25 == 0 or i == len(cards):
            print(f"  Progress: {i}/{len(cards)} ({tracked} tracked, {skipped_no_id + skipped_no_price} skipped)")
        
        # Get PokemonTCG.io ID
        external_ids = card.get('external_ids', {})
        if isinstance(external_ids, dict):
            pokemontcg_id = external_ids.get('pokemontcg_io')
        else:
            pokemontcg_id = None
        
        if not pokemontcg_id:
            skipped_no_id += 1
            continue
        
        # Fetch market price
        market_price_usd = fetch_current_market_price(pokemontcg_id)
        
        if market_price_usd is None:
            skipped_no_price += 1
            time.sleep(API_DELAY)  # Rate limiting
            continue
        
        # Calculate prices
        market_price_cad = market_price_usd * USD_TO_CAD
        
        # Apply condition multiplier for suggested price
        condition_multipliers = {
            'NM': 1.00,
            'LP': 0.80,
            'MP': 0.65,
            'HP': 0.50,
            'DMG': 0.35
        }
        condition_multiplier = condition_multipliers.get(card['condition'], 1.00)
        
        # Calculate suggested selling price
        base_price = round_up_to_nearest_50_cents(market_price_cad * MARKUP)
        suggested_price_cad = base_price if card['condition'] == 'NM' else round(base_price * condition_multiplier, 2)
        
        # Store in database
        success = store_price(
            card['card_id'],
            card['condition'],
            market_price_usd,
            market_price_cad,
            suggested_price_cad
        )
        
        if success:
            tracked += 1
        else:
            errors += 1
        
        # Rate limiting
        time.sleep(API_DELAY)
    
    print()
    print("="*70)
    print("✅ TRACKING COMPLETE")
    print("="*70)
    print(f"📊 Summary:")
    print(f"  • Total variants: {len(cards)}")
    print(f"  • Successfully tracked: {tracked}")
    print(f"  • Skipped (no API ID): {skipped_no_id}")
    print(f"  • Skipped (no price data): {skipped_no_price}")
    print(f"  • Errors: {errors}")
    print()
    
    return {
        'total_cards': len(cards),
        'tracked': tracked,
        'skipped_no_id': skipped_no_id,
        'skipped_no_price': skipped_no_price,
        'errors': errors
    }


def main():
    """Main execution"""
    try:
        result = track_prices()
        
        # Exit code based on success
        if result['errors'] > 0:
            print(f"⚠️  Completed with {result['errors']} errors")
            return 1
        else:
            print(f"🎉 All done! Tracked {result['tracked']} prices successfully.")
            return 0
            
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
