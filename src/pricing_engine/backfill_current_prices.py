"""
Backfill Current Prices
Dumpling Collectibles

One-time script to seed price_history with current prices
Sets the date to last Friday so you can get reports immediately

Usage:
    python backfill_current_prices.py
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Import the tracker
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from daily_price_tracker import get_cards_with_inventory, fetch_current_market_price, round_up_to_nearest_50_cents

load_dotenv()

DATABASE_URL = os.getenv('NEON_DB_URL')
USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))
MARKUP = float(os.getenv('MARKUP', '1.10'))


def get_last_friday():
    """Get the date of last Friday"""
    today = datetime.now()
    
    # If today is Friday, use last Friday (7 days ago)
    # Otherwise, find the most recent Friday
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0:
        # Today is Friday, go back 7 days
        last_friday = today - timedelta(days=7)
    else:
        # Go back to most recent Friday
        last_friday = today - timedelta(days=days_since_friday)
    
    # Set to 1 PM (13:00)
    last_friday = last_friday.replace(hour=13, minute=0, second=0, microsecond=0)
    
    return last_friday


def store_backfill_price(card_id, condition, market_price_usd, market_price_cad, suggested_price_cad, backfill_date):
    """
    Store price with custom date (for backfill)
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (card_id, condition, DATE(%s)) 
            DO UPDATE SET
                market_price_usd = EXCLUDED.market_price_usd,
                market_price_cad = EXCLUDED.market_price_cad,
                suggested_price_cad = EXCLUDED.suggested_price_cad
        """, (
            card_id,
            condition,
            market_price_usd,
            market_price_cad,
            suggested_price_cad,
            'pokemontcg_io',
            backfill_date,
            backfill_date
        ))
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"  ❌ Error: {str(e)[:50]}")
        return False
        
    finally:
        cursor.close()
        conn.close()


def main():
    """Main backfill execution"""
    print("="*70)
    print("🔄 BACKFILL CURRENT PRICES")
    print("="*70)
    print()
    
    # Calculate last Friday
    last_friday = get_last_friday()
    print(f"📅 Backfill date: {last_friday.strftime('%Y-%m-%d %I:%M %p')}")
    print(f"   (Last Friday at 1 PM)")
    print()
    
    # Get cards
    print("📦 Fetching cards with inventory...")
    cards = get_cards_with_inventory()
    print(f"✅ Found {len(cards)} card variants")
    print()
    
    if not cards:
        print("ℹ️  No cards to backfill.")
        return
    
    # Confirm before proceeding
    print(f"⚠️  This will add {len(cards)} price records to price_history")
    print(f"   with date: {last_friday.strftime('%Y-%m-%d')}")
    print()
    response = input("Continue? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("❌ Backfill cancelled.")
        return
    
    print()
    print("🔍 Fetching current prices...")
    print()
    
    tracked = 0
    skipped = 0
    errors = 0
    
    for i, card in enumerate(cards, 1):
        if i % 25 == 0 or i == len(cards):
            print(f"  Progress: {i}/{len(cards)} ({tracked} tracked)")
        
        # Get PokemonTCG.io ID
        external_ids = card.get('external_ids', {})
        if isinstance(external_ids, dict):
            pokemontcg_id = external_ids.get('pokemontcg_io')
        else:
            pokemontcg_id = None
        
        if not pokemontcg_id:
            skipped += 1
            continue
        
        # Fetch market price
        market_price_usd = fetch_current_market_price(pokemontcg_id)
        
        if market_price_usd is None:
            skipped += 1
            continue
        
        # Calculate prices
        market_price_cad = market_price_usd * USD_TO_CAD
        
        condition_multipliers = {
            'NM': 1.00,
            'LP': 0.80,
            'MP': 0.65,
            'HP': 0.50,
            'DMG': 0.35
        }
        condition_multiplier = condition_multipliers.get(card['condition'], 1.00)
        
        base_price = round_up_to_nearest_50_cents(market_price_cad * MARKUP)
        suggested_price_cad = base_price if card['condition'] == 'NM' else round(base_price * condition_multiplier, 2)
        
        # Store with backfill date
        success = store_backfill_price(
            card['card_id'],
            card['condition'],
            market_price_usd,
            market_price_cad,
            suggested_price_cad,
            last_friday
        )
        
        if success:
            tracked += 1
        else:
            errors += 1
        
        # Small delay to avoid rate limits
        import time
        time.sleep(0.1)
    
    print()
    print("="*70)
    print("✅ BACKFILL COMPLETE")
    print("="*70)
    print(f"📊 Summary:")
    print(f"  • Total variants: {len(cards)}")
    print(f"  • Successfully backfilled: {tracked}")
    print(f"  • Skipped: {skipped}")
    print(f"  • Errors: {errors}")
    print()
    print(f"🎉 Price history seeded with data from {last_friday.strftime('%Y-%m-%d')}")
    print()
    print("📧 Next steps:")
    print("  1. Run daily_price_tracker.py to track today's prices")
    print("  2. Run generate_price_report.py to see your first report")
    print("  3. Wait for Friday 1 PM for automatic weekly reports!")


if __name__ == "__main__":
    main()
