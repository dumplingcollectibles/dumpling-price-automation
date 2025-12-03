"""
Issue Store Credit - Shopify Gift Card System

Creates Shopify gift cards for buylist payouts and tracks in database ledger.

Usage:
  python issue_store_credit.py
"""

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
STORE_NAME = os.getenv('STORE_NAME', 'Dumpling Collectibles')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"


def find_or_create_user(email, conn):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    
    if user:
        user_id = user['id']
        print(f"   ✅ Found existing user (ID: {user_id})")
    else:
        cursor.execute("INSERT INTO users (email, created_at, updated_at) VALUES (%s, NOW(), NOW()) RETURNING id", (email,))
        user_id = cursor.fetchone()['id']
        conn.commit()
        print(f"   ✅ Created new user (ID: {user_id})")
    
    cursor.close()
    return user_id


def get_current_balance(user_id, conn):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT balance_after FROM store_credit_ledger WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT 1", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    return float(result['balance_after']) if result else 0.0


def create_gift_card(amount, customer_email, note):
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/gift_cards.json"
    
    try:
        response = requests.post(
            url,
            json={'gift_card': {'initial_value': str(amount), 'note': note}},
            headers={'X-Shopify-Access-Token': SHOPIFY_ACCESS_TOKEN, 'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            gift_card = response.json()['gift_card']
            return {'code': gift_card['code'], 'id': gift_card['id'], 'balance': gift_card['balance']}
        else:
            return {'error': f'Shopify API error: {response.status_code}'}
    except Exception as e:
        return {'error': str(e)}


def record_in_ledger(user_id, amount, gift_card_code, reference_type, reference_id, notes, conn):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    current_balance = get_current_balance(user_id, conn)
    new_balance = current_balance + amount
    
    cursor.execute("""
        INSERT INTO store_credit_ledger (user_id, amount, transaction_type, reference_type, reference_id, 
                                         balance_after, shopify_gift_card_code, notes, created_at)
        VALUES (%s, %s, 'buylist_payout', %s, %s, %s, %s, %s, NOW())
        RETURNING id
    """, (user_id, amount, reference_type, reference_id, new_balance, gift_card_code, notes))
    
    ledger_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    return ledger_id, new_balance


def main():
    print("=" * 70)
    print("💳 ISSUE STORE CREDIT")
    print("=" * 70)
    print()
    
    if not SHOPIFY_ACCESS_TOKEN or not SHOPIFY_SHOP_URL:
        print("❌ Error: Shopify credentials not configured!")
        return
    
    customer_email = input("Enter customer email: ").strip()
    if not customer_email or '@' not in customer_email:
        print("❌ Invalid email!")
        return
    
    try:
        amount = float(input("Enter amount (CAD): $").strip())
        if amount <= 0:
            print("❌ Amount must be positive!")
            return
    except ValueError:
        print("❌ Invalid amount!")
        return
    
    reference_type = input("Reference type (buy_offer/manual/refund) [buy_offer]: ").strip() or 'buy_offer'
    
    if reference_type == 'buy_offer':
        try:
            reference_id = int(input("Buy offer ID: ").strip())
        except ValueError:
            print("❌ Invalid ID!")
            return
    else:
        reference_id = None
    
    notes = input("Notes: ").strip() or f"Store credit for {customer_email}"
    
    print()
    print(f"Customer: {customer_email}")
    print(f"Amount: ${amount:.2f}")
    print(f"Reference: {reference_type}" + (f" #{reference_id}" if reference_id else ""))
    print()
    
    if input("Create gift card? (yes/no): ").strip().lower() not in ['yes', 'y']:
        print("❌ Cancelled")
        return
    
    print("\n⚙️  Processing...\n")
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        user_id = find_or_create_user(customer_email, conn)
        current_balance = get_current_balance(user_id, conn)
        
        gift_card = create_gift_card(amount, customer_email, notes)
        if 'error' in gift_card:
            print(f"❌ Failed: {gift_card['error']}")
            conn.close()
            return
        
        ledger_id, new_balance = record_in_ledger(user_id, amount, gift_card['code'], reference_type, reference_id, notes, conn)
        conn.close()
        
        print("=" * 70)
        print("✅ SUCCESS!")
        print("=" * 70)
        print(f"\nGift Card Code: {gift_card['code']}")
        print(f"Amount: ${amount:.2f}")
        print(f"Balance: ${current_balance:.2f} → ${new_balance:.2f}\n")
        
        print("📧 EMAIL TO CUSTOMER:")
        print("-" * 70)
        print(f"Subject: Your Store Credit - ${amount:.2f}\n")
        print(f"Hi,\n")
        print(f"Your buylist has been approved!")
        print(f"Store Credit: ${amount:.2f}")
        print(f"Gift Card Code: {gift_card['code']}\n")
        print(f"Use at checkout on our store.")
        print(f"Total balance: ${new_balance:.2f}\n")
        print(f"Thanks,\n{STORE_NAME}")
        print("-" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
