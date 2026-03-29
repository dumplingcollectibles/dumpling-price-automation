"""
Issue Store Credit - Automated Version for GitHub Actions

Creates Shopify gift cards, records in database, sends email.
Accepts command-line arguments for automation.

Usage:
  python issue_store_credit_automated.py \
    --email john@example.com \
    --amount 10.00 \
    --type buylist_payout \
    --buylist-id 5 \
    --notes "Payment for buylist"
"""

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import sys
import argparse
from dotenv import load_dotenv

# Import email helper (must be in same directory)
try:
    from email_helper import send_gift_card_email
except ImportError:
    print("⚠️  email_helper.py not found - emails will not be sent")
    send_gift_card_email = None

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


def create_shopify_gift_card(amount, email):
    print("\n2️⃣ Creating gift card in Shopify...")
    
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/gift_cards.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }
    
    payload = {
        "gift_card": {
            "initial_value": float(amount),
            "code": None,
            "note": f"Store credit issued via GitHub Actions for {email}"
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 201:
        gift_card = response.json()['gift_card']
        print(f"   ✅ Gift card created successfully")
        print(f"   Code: {gift_card['code']}")
        print(f"   Balance: ${float(gift_card['balance']):.2f}")
        return gift_card['code']
    else:
        print(f"   ❌ Failed to create gift card: {response.status_code}")
        print(f"   Response: {response.text}")
        return None


def record_in_ledger(user_id, amount, transaction_type, reference_type, reference_id, gift_card_code, notes, conn):
    print("\n3️⃣ Recording in store_credit_ledger...")
    
    current_balance = get_current_balance(user_id, conn)
    new_balance = current_balance + float(amount)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO store_credit_ledger 
        (user_id, amount, transaction_type, reference_type, reference_id, balance_after, shopify_gift_card_code, notes, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """, (user_id, amount, transaction_type, reference_type, reference_id, new_balance, gift_card_code, notes))
    
    conn.commit()
    cursor.close()
    
    print(f"   ✅ Recorded in ledger")
    print(f"   Previous balance: ${current_balance:.2f}")
    print(f"   Amount added: ${amount:.2f}")
    print(f"   New balance: ${new_balance:.2f}")
    
    return new_balance


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Issue store credit via command line')
    parser.add_argument('--email', required=True, help='Customer email address')
    parser.add_argument('--amount', required=True, type=float, help='Amount in CAD')
    parser.add_argument('--type', required=True, choices=['buylist_payout', 'refund', 'adjustment', 'promotion'], 
                       help='Transaction type')
    parser.add_argument('--buylist-id', type=int, help='Buylist ID (optional)')
    parser.add_argument('--notes', help='Additional notes (optional)')
    
    args = parser.parse_args()
    
    # Validate inputs
    email = args.email.strip()
    if not email or '@' not in email:
        print("❌ Invalid email!")
        sys.exit(1)
    
    amount = args.amount
    if amount <= 0:
        print("❌ Amount must be positive!")
        sys.exit(1)
    
    transaction_type = args.type
    buylist_id = args.buylist_id
    notes = args.notes
    
    # Determine reference
    reference_type = 'buy_offer' if transaction_type == 'buylist_payout' and buylist_id else None
    reference_id = buylist_id if reference_type else None
    
    print("=" * 70)
    print(f"💳 ISSUE STORE CREDIT - {STORE_NAME}")
    print("=" * 70)
    print()
    print(f"Customer: {email}")
    print(f"Amount: ${amount:.2f}")
    print(f"Type: {transaction_type}")
    if reference_id:
        print(f"Reference: {reference_type} #{reference_id}")
    if notes:
        print(f"Notes: {notes}")
    print()
    
    # Process
    try:
        conn = psycopg2.connect(DATABASE_URL)
        
        # Step 1: Find/create user
        print("1️⃣ Looking up customer...")
        user_id = find_or_create_user(email, conn)
        
        # Step 2: Create Shopify gift card
        gift_card_code = create_shopify_gift_card(amount, email)
        
        if not gift_card_code:
            print("\n❌ Failed to create gift card!")
            conn.close()
            sys.exit(1)
        
        # Step 3: Record in ledger
        new_balance = record_in_ledger(
            user_id, amount, transaction_type, 
            reference_type, reference_id, 
            gift_card_code, notes, conn
        )
        
        # Step 4: Send email
        print("\n4️⃣ Sending email to customer...")
        
        if send_gift_card_email:
            email_sent = send_gift_card_email(
                customer_email=email,
                gift_card_code=gift_card_code,
                amount=amount,
                reason=notes,
                balance_after=new_balance
            )
            
            if email_sent:
                print(f"   ✅ Email sent successfully to {email}")
            else:
                print(f"   ⚠️  Email not sent (check configuration)")
        else:
            print(f"   ⚠️  Email helper not available")
        
        conn.close()
        
        # Success summary
        print("\n" + "=" * 70)
        print("✅ STORE CREDIT ISSUED SUCCESSFULLY!")
        print("=" * 70)
        print()
        print(f"Customer: {email}")
        print(f"Gift Card Code: {gift_card_code}")
        print(f"Amount: ${amount:.2f}")
        print(f"New Balance: ${new_balance:.2f}")
        print()
        
        # Exit successfully
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
