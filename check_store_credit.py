"""
Check Store Credit Balance

Query customer's store credit balance and transaction history.

Usage:
  python check_store_credit.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('NEON_DB_URL')


def find_user(email, conn):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, email, name FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    return user


def get_credit_history(user_id, conn):
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT id, amount, transaction_type, reference_type, reference_id, 
               balance_after, shopify_gift_card_code, notes, created_at
        FROM store_credit_ledger
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
    """, (user_id,))
    transactions = cursor.fetchall()
    cursor.close()
    return transactions


def format_transaction_type(trans_type):
    types = {
        'buylist_payout': '💰 Buylist Payout',
        'order_payment': '🛒 Order Payment',
        'adjustment': '✏️  Adjustment',
        'refund': '↩️  Refund'
    }
    return types.get(trans_type, trans_type)


def main():
    print("=" * 70)
    print("💳 CHECK STORE CREDIT BALANCE")
    print("=" * 70)
    print()
    
    customer_email = input("Enter customer email: ").strip()
    
    if not customer_email or '@' not in customer_email:
        print("❌ Invalid email!")
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    user = find_user(customer_email, conn)
    
    if not user:
        print(f"❌ Customer not found: {customer_email}")
        conn.close()
        return
    
    transactions = get_credit_history(user['id'], conn)
    
    if not transactions:
        print(f"\nCustomer: {customer_email}")
        print("Current Balance: $0.00")
        print("\nNo transaction history.")
        conn.close()
        return
    
    current_balance = float(transactions[0]['balance_after'])
    total_issued = sum(float(t['amount']) for t in transactions if float(t['amount']) > 0)
    total_used = abs(sum(float(t['amount']) for t in transactions if float(t['amount']) < 0))
    
    print("=" * 70)
    print("📊 STORE CREDIT REPORT")
    print("=" * 70)
    print()
    print(f"Customer: {customer_email}")
    print(f"Name: {user['name'] or 'N/A'}")
    print()
    print(f"💰 Current Balance: ${current_balance:.2f}")
    print()
    
    print("📜 Transaction History:")
    print("-" * 70)
    print(f"{'Date':<20} {'Type':<25} {'Amount':<12} {'Balance':<12}")
    print("-" * 70)
    
    for trans in transactions:
        date_str = trans['created_at'].strftime('%Y-%m-%d %H:%M')
        trans_type = format_transaction_type(trans['transaction_type'])
        amount = float(trans['amount'])
        balance = float(trans['balance_after'])
        
        amount_str = f"${amount:+.2f}" if amount != 0 else "$0.00"
        print(f"{date_str:<20} {trans_type:<25} {amount_str:<12} ${balance:.2f}")
        
        if trans['notes']:
            notes = trans['notes']
            if len(notes) > 60:
                notes = notes[:57] + "..."
            print(f"{'':>20} └─ {notes}")
    
    print("-" * 70)
    print()
    print("📊 Summary:")
    print("-" * 70)
    print(f"Total Credit Issued:  ${total_issued:.2f}")
    print(f"Total Credit Used:    ${total_used:.2f}")
    print(f"Current Balance:      ${current_balance:.2f}")
    print(f"Total Transactions:   {len(transactions)}")
    print()
    
    conn.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
