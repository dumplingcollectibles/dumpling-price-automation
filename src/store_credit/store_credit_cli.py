"""
Store Credit CLI Controller

Command-line interface to check, issue, and adjust store credit balances.
It leverages the centralized StoreCreditService instead of running raw SQL.

Usage:
  python store_credit_cli.py check --email john@example.com
  python store_credit_cli.py issue --email john@example.com --amount 50.00 --type refund --notes "Return" --gift-card
"""

import sys
import argparse
from src.store_credit.store_credit_service import StoreCreditService
from src.config import config

def format_transaction_type(trans_type):
    types = {
        'buylist_payout': '💰 Buylist Payout',
        'order_payment': '🛒 Order Payment',
        'adjustment': '✏️  Adjustment',
        'refund': '↩️  Refund'
    }
    return types.get(trans_type, trans_type)


def handle_check(args, service):
    print("=" * 70)
    print("💳 CHECK STORE CREDIT BALANCE")
    print("=" * 70)
    print()
    
    user = service.find_user(args.email)
    if not user:
        print(f"❌ Customer not found: {args.email}")
        return
        
    transactions = service.get_history(user['id'])
    
    if not transactions:
        print(f"\nCustomer: {args.email}")
        print("Current Balance: $0.00\n\nNo transaction history.")
        return
        
    current_balance = float(transactions[0]['balance_after'])
    total_issued = sum(float(t['amount']) for t in transactions if float(t['amount']) > 0)
    total_used = abs(sum(float(t['amount']) for t in transactions if float(t['amount']) < 0))
    
    print(f"Customer: {args.email}")
    print(f"Name: {user['name'] or 'N/A'}")
    print(f"💰 Current Balance: ${current_balance:.2f}\n")
    print("📜 Transaction History:")
    print("-" * 70)
    print(f"{'Date':<20} {'Type':<25} {'Amount':<12} {'Balance':<12}")
    print("-" * 70)
    
    for trans in transactions:
        date_str = trans['created_at'].strftime('%Y-%m-%d %H:%M')
        t_type = format_transaction_type(trans['transaction_type'])
        amount = float(trans['amount'])
        balance = float(trans['balance_after'])
        
        amount_str = f"${amount:+.2f}" if amount != 0 else "$0.00"
        print(f"{date_str:<20} {t_type:<25} {amount_str:<12} ${balance:.2f}")
        
        if trans['notes']:
            notes = trans['notes'][:57] + "..." if len(trans['notes']) > 60 else trans['notes']
            print(f"{'':>20} └─ {notes}")
    
    print("-" * 70)
    print("📊 Summary:")
    print(f"Total Credit Issued:  ${total_issued:.2f}")
    print(f"Total Credit Used:    ${total_used:.2f}")
    print(f"Current Balance:      ${current_balance:.2f}")
    print(f"Total Transactions:   {len(transactions)}")
    

def handle_issue(args, service):
    print("=" * 70)
    print(f"💳 ISSUE STORE CREDIT - {config.STORE_NAME}")
    print("=" * 70)
    
    print(f"Customer: {args.email}")
    print(f"Amount: ${args.amount:+.2f}")
    print(f"Type: {args.type}")
    print(f"Reason: {args.notes}")
    if args.gift_card:
        print("Create Gift Card: Yes")
        
    try:
        result = service.issue_credit(
            email=args.email,
            amount=args.amount,
            transaction_type=args.type,
            reason=args.notes,
            create_gift_card=args.gift_card,
            reference_type='buy_offer' if (args.buylist_id and args.buylist_id.strip() != "") else None,
            reference_id=int(args.buylist_id) if (args.buylist_id and args.buylist_id.strip() != "") else None,
            notify=args.notify
        )
        
        print("\n" + "=" * 70)
        print("✅ STORE CREDIT ADJUSTED SUCCESSFULLY!")
        print("=" * 70)
        print(f"Previous Balance: ${result['old_balance']:.2f}")
        print(f"New Balance: ${result['new_balance']:.2f}")
        if result['gift_card_code']:
            print(f"Gift Card Code: {result['gift_card_code']}")
        if result['email_sent']:
            print("Customer Email: 📤 Sent successfully!")
            
    except Exception as e:
        print(f"\n❌ Failed to issue credit: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Store Credit CLI Controller')
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # "check" command
    check_parser = subparsers.add_parser('check', help='Check user balance')
    check_parser.add_argument('--email', required=True, help='Customer email address')
    
    # "issue" / "adjust" command
    issue_parser = subparsers.add_parser('issue', help='Issue or adjust store credit')
    issue_parser.add_argument('--email', required=True, help='Customer email address')
    issue_parser.add_argument('--amount', required=True, type=float, help='Amount (CAD)')
    issue_parser.add_argument('--type', required=True, choices=['buylist_payout', 'refund', 'adjustment', 'promotion', 'order_payment'], help='Transaction type')
    issue_parser.add_argument('--notes', required=False, default="", help='Reason for adjustment')
    issue_parser.add_argument('--buylist-id', type=str, default="", help='Buylist ID reference (optional)')
    issue_parser.add_argument('--gift-card', action='store_true', help='Generate Shopify gift card')
    issue_parser.add_argument('--notify', action='store_true', help='Send Brevo email to user regarding the credit')
    
    args = parser.parse_args()
    
    # Initialize the centralized Service
    try:
        service = StoreCreditService()
    except Exception as e:
        print(f"❌ Failed to reach database: {e}")
        sys.exit(1)
        
    if args.command == 'check':
        handle_check(args, service)
    elif args.command == 'issue':
        handle_issue(args, service)


if __name__ == "__main__":
    main()
