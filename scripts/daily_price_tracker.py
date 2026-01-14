"""
Daily Price Tracker - Database Copy Version (Fixed)
Copies prices from variants table to price_history

NO API calls needed!

Usage:
    python daily_price_tracker.py
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))


def track_prices_from_database():
    """
    Copy current prices from variants table to price_history
    This creates a historical snapshot of your pricing
    """
    print("="*70)
    print("📊 DAILY PRICE TRACKER (Database Copy)")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print()
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        print("📦 Getting cards with inventory and prices...")
        
        # Get all cards with inventory and their current prices
        cursor.execute("""
            SELECT 
                c.id as card_id,
                c.name as card_name,
                c.set_code,
                c.number,
                v.id as variant_id,
                v.condition,
                v.inventory_qty,
                v.price_cad,
                v.cost_basis_avg
            FROM cards c
            JOIN products p ON p.card_id = c.id
            JOIN variants v ON v.product_id = p.id
            WHERE v.inventory_qty > 0
            AND c.language = 'English'
            AND v.price_cad IS NOT NULL
            AND v.price_cad > 0
            ORDER BY c.set_code, c.number, v.condition
        """)
        
        cards = cursor.fetchall()
        
        print(f"✅ Found {len(cards)} card variants with prices")
        print()
        
        if not cards:
            print("ℹ️  No cards with prices found.")
            cursor.close()
            conn.close()
            return {
                'total_cards': 0,
                'tracked': 0,
                'skipped': 0,
                'errors': 0
            }
        
        print("💾 Storing price snapshots...")
        
        tracked = 0
        updated = 0
        errors = 0
        
        # Process each card
        for card in cards:
            try:
                # Convert CAD price back to USD for storage
                price_cad = float(card['price_cad'])
                market_price_usd = price_cad / USD_TO_CAD
                
                # Check if entry already exists for today
                cursor.execute("""
                    SELECT id 
                    FROM price_history 
                    WHERE card_id = %s 
                    AND condition = %s 
                    AND DATE(checked_at) = CURRENT_DATE
                """, (card['card_id'], card['condition']))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing entry
                    cursor.execute("""
                        UPDATE price_history
                        SET market_price_usd = %s,
                            market_price_cad = %s,
                            suggested_price_cad = %s,
                            checked_at = NOW()
                        WHERE id = %s
                    """, (
                        market_price_usd,
                        price_cad,
                        price_cad,
                        existing['id']
                    ))
                    updated += 1
                else:
                    # Insert new entry
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
                    """, (
                        card['card_id'],
                        card['condition'],
                        market_price_usd,
                        price_cad,
                        price_cad,
                        'database_copy'
                    ))
                    tracked += 1
                
                # Show progress
                total_processed = tracked + updated
                if total_processed % 50 == 0:
                    print(f"  Progress: {total_processed}/{len(cards)}")
                
            except Exception as e:
                errors += 1
                print(f"  ⚠️  Error storing {card['card_name']}: {str(e)[:80]}")
                # Don't continue - rollback this card but keep going
                conn.rollback()
                # Start new transaction
                continue
        
        # Commit all successful changes
        conn.commit()
        
        print()
        print("="*70)
        print("✅ TRACKING COMPLETE")
        print("="*70)
        print(f"📊 Summary:")
        print(f"  • Total variants: {len(cards)}")
        print(f"  • New records created: {tracked}")
        print(f"  • Existing records updated: {updated}")
        print(f"  • Errors: {errors}")
        print()
        
        return {
            'total_cards': len(cards),
            'tracked': tracked + updated,
            'skipped': 0,
            'errors': errors
        }
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'total_cards': 0,
            'tracked': 0,
            'skipped': 0,
            'errors': 1
        }
        
    finally:
        cursor.close()
        conn.close()


def main():
    """Main execution"""
    try:
        result = track_prices_from_database()
        
        # Exit code based on success
        if result['tracked'] > 0:
            print(f"🎉 Success! Tracked {result['tracked']} prices.")
            return 0
        elif result['errors'] > 0:
            print(f"⚠️  Completed with {result['errors']} errors")
            return 1
        else:
            print(f"ℹ️  No prices to track.")
            return 0
            
    except Exception as e:
        print(f"❌ Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
