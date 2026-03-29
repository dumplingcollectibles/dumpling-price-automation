"""
Adjust Store Credit - Automated Version for GitHub Actions

Adds or removes store credit for adjustments, refunds, or corrections.
Can optionally create Shopify gift card for additions.

Usage:
  python adjust_store_credit.py \
    --email john@example.com \
    --amount 10.00 \
    --reason "Refund for order #1234" \
    --create-gift-card
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
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


def find_user(email, conn):
    """Find user by email"""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    
    if user:
        return user['id']
    else:
        return None


def get_current_balance(user_id, conn):
    """Get user's current store credit balance"""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT balance_after FROM store_credit_ledger WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,)
    )
    result = cursor.fetchone()
    cursor.close()
    return float(result['balance_after']) if result else 0.0


def create_shopify_gift_card(amount, email):
    """Create gift card in Shopify"""
    print("   Creating Shopify gift card...")
    
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/gift_cards.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }
    
    payload = {
        "gift_card": {
            "initial_value": float(amount),
            "code": None,
            "note": f"Store credit adjustment for {email}"
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 201:
        gift_card = response.json()['gift_card']
        print(f"   ✅ Gift card created: {gift_card['code']}")
        return gift_card['code']
    else:
        print(f"   ⚠️  Failed to create gift card: {response.status_code}")
        return None


def record_adjustment(user_id, amount, reason, gift_card_code, conn):
    """Record credit adjustment in ledger"""
    current_balance = get_current_balance(user_id, conn)
    new_balance = current_balance + float(amount)
    
    # Determine transaction type based on amount
    if float(amount) > 0:
        transaction_type = 'adjustment'  # Adding credit
    else:
        transaction_type = 'order_payment'  # Removing credit (like an order)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO store_credit_ledger 
        (user_id, amount, transaction_type, reference_type, reference_id, 
         balance_after, shopify_gift_card_code, notes, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """, (user_id, amount, transaction_type, 'manual', None, new_balance, gift_card_code, reason))
    
    conn.commit()
    cursor.close()
    
    return current_balance, new_balance


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Adjust store credit')
    parser.add_argument('--email', required=True, help='Customer email address')
    parser.add_argument('--amount', required=True, type=float, help='Amount to add (positive) or remove (negative)')
    parser.add_argument('--reason', required=True, help='Reason for adjustment')
    parser.add_argument('--create-gift-card', action='store_true', 
                       help='Create Shopify gift card (only for additions)')
    
    args = parser.parse_args()
    
    # Validate inputs
    email = args.email.strip()
    if not email or '@' not in email:
        print("❌ Invalid email!")
        sys.exit(1)
    
    amount = args.amount
    if amount == 0:
        print("❌ Amount cannot be zero!")
        sys.exit(1)
    
    reason = args.reason
    create_gift_card = args.create_gift_card
    
    # Can only create gift card for positive amounts
    if create_gift_card and amount < 0:
        print("⚠️  Cannot create gift card for negative adjustment - ignoring flag")
        create_gift_card = False
    
    print("=" * 70)
    print(f"💳 ADJUST STORE CREDIT - {STORE_NAME}")
    print("=" * 70)
    print()
    print(f"Customer: {email}")
    print(f"Adjustment: ${amount:+.2f}")  # +/- sign
    print(f"Reason: {reason}")
    if create_gift_card:
        print(f"Create Gift Card: Yes")
    print()
    
    # Process
    try:
        conn = psycopg2.connect(DATABASE_URL)
        
        # Step 1: Find user
        print("1️⃣ Looking up customer...")
        user_id = find_user(email, conn)
        
        if not user_id:
            print(f"   ❌ Customer not found: {email}")
            print(f"   💡 Create user first with issue_store_credit script")
            conn.close()
            sys.exit(1)
        
        print(f"   ✅ Found user (ID: {user_id})")
        
        # Step 2: Create gift card if requested (for additions only)
        gift_card_code = None
        if create_gift_card and amount > 0:
            print("\n2️⃣ Creating Shopify gift card...")
            gift_card_code = create_shopify_gift_card(amount, email)
            if not gift_card_code:
                print("   ⚠️  Continuing without gift card...")
        else:
            print("\n2️⃣ Skipping gift card creation")
            if amount < 0:
                print("   (Removing credit - no gift card needed)")
            else:
                print("   (Use --create-gift-card flag to create one)")
        
        # Step 3: Record adjustment
        print("\n3️⃣ Recording adjustment in ledger...")
        old_balance, new_balance = record_adjustment(user_id, amount, reason, gift_card_code, conn)
        
        print(f"   ✅ Adjustment recorded")
        print(f"   Previous balance: ${old_balance:.2f}")
        print(f"   Adjustment: ${amount:+.2f}")
        print(f"   New balance: ${new_balance:.2f}")
        
        # Step 4: Send email if adding credit and gift card created
        if send_gift_card_email and gift_card_code and amount > 0:
            print("\n4️⃣ Sending email to customer...")
            email_sent = send_gift_card_email(
                customer_email=email,
                gift_card_code=gift_card_code,
                amount=amount,
                reason=reason,
                balance_after=new_balance
            )
            
            if email_sent:
                print(f"   ✅ Email sent successfully to {email}")
            else:
                print(f"   ⚠️  Email not sent")
        else:
            print("\n4️⃣ Skipping email")
            if amount < 0:
                print("   (Credit removed - no email needed)")
            elif not gift_card_code:
                print("   (No gift card to send)")
        
        conn.close()
        
        # Success summary
        print("\n" + "=" * 70)
        print("✅ STORE CREDIT ADJUSTED SUCCESSFULLY!")
        print("=" * 70)
        print()
        print(f"Customer: {email}")
        print(f"Adjustment: ${amount:+.2f}")
        print(f"Previous Balance: ${old_balance:.2f}")
        print(f"New Balance: ${new_balance:.2f}")
        if gift_card_code:
            print(f"Gift Card Code: {gift_card_code}")
        print(f"Reason: {reason}")
        print()
        
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
