"""
Test script to verify database setup before using add_inventory_single.py

This checks:
1. Database connection works
2. All required tables exist
3. Sample cards exist to add inventory to
4. Shopify credentials are configured

Usage:
    python test_inventory_setup.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')


def test_database_connection():
    """Test if database connection works"""
    print("\n1️⃣  Testing database connection...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        print("   ✅ Database connection successful!")
        return True
    except Exception as e:
        print(f"   ❌ Database connection failed: {str(e)}")
        return False


def test_tables_exist():
    """Test if all required tables exist"""
    print("\n2️⃣  Checking required tables...")
    
    required_tables = [
        'cards',
        'products',
        'variants',
        'inventory_transactions'
    ]
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        for table in required_tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table,))
            
            exists = cursor.fetchone()[0]
            
            if exists:
                print(f"   ✅ Table '{table}' exists")
            else:
                print(f"   ❌ Table '{table}' missing!")
                return False
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking tables: {str(e)}")
        return False


def test_sample_cards():
    """Test if there are cards in the database"""
    print("\n3️⃣  Checking for cards in database...")
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Count total cards
        cursor.execute("SELECT COUNT(*) as count FROM cards")
        card_count = cursor.fetchone()['count']
        
        print(f"   📊 Total cards: {card_count}")
        
        if card_count == 0:
            print("   ⚠️  No cards in database! Run product upload script first.")
            return False
        
        # Count cards with Shopify products
        cursor.execute("""
            SELECT COUNT(DISTINCT c.id) as count
            FROM cards c
            JOIN products p ON p.card_id = c.id
            WHERE p.shopify_product_id IS NOT NULL
        """)
        shopify_card_count = cursor.fetchone()['count']
        
        print(f"   📊 Cards in Shopify: {shopify_card_count}")
        
        if shopify_card_count == 0:
            print("   ⚠️  No cards synced to Shopify! Shopify sync will be skipped.")
        
        # Show sample cards
        cursor.execute("""
            SELECT c.name, c.set_code, c.number
            FROM cards c
            LIMIT 5
        """)
        
        sample_cards = cursor.fetchall()
        
        print("\n   📋 Sample cards you can add inventory to:")
        for card in sample_cards:
            print(f"      • {card['name']} ({card['set_code']}-{card['number']})")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"   ❌ Error checking cards: {str(e)}")
        return False


def test_shopify_credentials():
    """Test if Shopify credentials are configured"""
    print("\n4️⃣  Checking Shopify configuration...")
    
    all_good = True
    
    if SHOPIFY_SHOP_URL:
        print(f"   ✅ SHOPIFY_SHOP_URL: {SHOPIFY_SHOP_URL}")
    else:
        print("   ⚠️  SHOPIFY_SHOP_URL not set (Shopify sync will be skipped)")
        all_good = False
    
    if SHOPIFY_ACCESS_TOKEN:
        print(f"   ✅ SHOPIFY_ACCESS_TOKEN: {SHOPIFY_ACCESS_TOKEN[:10]}...")
    else:
        print("   ⚠️  SHOPIFY_ACCESS_TOKEN not set (Shopify sync will be skipped)")
        all_good = False
    
    if SHOPIFY_LOCATION_ID:
        print(f"   ✅ SHOPIFY_LOCATION_ID: {SHOPIFY_LOCATION_ID}")
    else:
        print("   ⚠️  SHOPIFY_LOCATION_ID not set (Shopify sync will be skipped)")
        all_good = False
    
    if not all_good:
        print("\n   💡 Tip: You can still add inventory without Shopify sync.")
        print("      Just update Shopify manually later, or add the credentials.")
    
    return True  # Not critical


def main():
    print("=" * 70)
    print("🧪 INVENTORY SYSTEM SETUP TEST")
    print("=" * 70)
    
    results = []
    
    # Run tests
    results.append(("Database Connection", test_database_connection()))
    results.append(("Required Tables", test_tables_exist()))
    results.append(("Sample Cards", test_sample_cards()))
    results.append(("Shopify Config", test_shopify_credentials()))
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(result[1] for result in results[:3])  # Shopify is optional
    
    print("\n" + "=" * 70)
    
    if all_passed:
        print("🎉 ALL CRITICAL TESTS PASSED!")
        print("\nYou're ready to add inventory!")
        print("\nRun: python add_inventory_single.py")
    else:
        print("❌ SOME TESTS FAILED")
        print("\nPlease fix the issues above before adding inventory.")
        print("\nCommon fixes:")
        print("• Check NEON_DB_URL in .env file")
        print("• Make sure database schema is created")
        print("• Run product upload script to add cards")
    
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
