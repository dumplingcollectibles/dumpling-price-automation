"""
Weekly Price Change Report Generator (with Price History)
Dumpling Collectibles

Compares current prices vs prices from 7 days ago
Only reports cards with inventory > 0

Usage:
    python generate_price_report_v2.py
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

DATABASE_URL = os.getenv('NEON_DB_URL')
SIGNIFICANT_CHANGE_PERCENT = 5.0
SIGNIFICANT_CHANGE_AMOUNT = 2.00


def get_price_at_date(card_id, condition, target_date):
    """Get price from price_history at specific date (or closest date before)"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                market_price_usd,
                market_price_cad,
                suggested_price_cad,
                checked_at
            FROM price_history
            WHERE card_id = %s
            AND condition = %s
            AND checked_at <= %s
            ORDER BY checked_at DESC
            LIMIT 1
        """, (card_id, condition, target_date))
        
        return cursor.fetchone()
        
    finally:
        cursor.close()
        conn.close()


def get_latest_prices_for_inventory():
    """Get latest prices for all cards with inventory"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            WITH latest_prices AS (
                SELECT DISTINCT ON (card_id, condition)
                    card_id,
                    condition,
                    market_price_usd,
                    market_price_cad,
                    suggested_price_cad,
                    checked_at
                FROM price_history
                ORDER BY card_id, condition, checked_at DESC
            )
            SELECT 
                c.id as card_id,
                c.name as card_name,
                c.set_code,
                c.set_name,
                c.number,
                v.id as variant_id,
                v.condition,
                v.inventory_qty,
                v.price_cad as current_shopify_price,
                v.cost_basis_avg,
                lp.market_price_usd as latest_market_usd,
                lp.market_price_cad as latest_market_cad,
                lp.suggested_price_cad as latest_suggested,
                lp.checked_at as latest_check_date
            FROM cards c
            JOIN products p ON p.card_id = c.id
            JOIN variants v ON v.product_id = p.id
            LEFT JOIN latest_prices lp ON lp.card_id = c.id AND lp.condition = v.condition
            WHERE v.inventory_qty > 0
            AND c.language = 'English'
            ORDER BY c.set_code, c.number, v.condition
        """)
        
        return cursor.fetchall()
        
    finally:
        cursor.close()
        conn.close()


def calculate_price_changes():
    """Compare current prices vs 7 days ago"""
    print(f"📊 Analyzing price changes...")
    print()
    
    # Get today and 7 days ago
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    
    print(f"📅 Comparing:")
    print(f"   Today: {now.strftime('%Y-%m-%d %I:%M %p')}")
    print(f"   vs")
    print(f"   7 days ago: {seven_days_ago.strftime('%Y-%m-%d %I:%M %p')}")
    print()
    
    # Get latest prices for all inventory
    cards = get_latest_prices_for_inventory()
    print(f"📦 Found {len(cards)} card variants with inventory")
    print()
    
    price_drops = []
    price_increases = []
    no_changes = []
    no_history = []
    
    print("🔍 Checking price history...")
    for i, card in enumerate(cards, 1):
        if i % 50 == 0:
            print(f"   Progress: {i}/{len(cards)}")
        
        # Get price from 7 days ago
        old_price_data = get_price_at_date(
            card['card_id'],
            card['condition'],
            seven_days_ago
        )
        
        if not old_price_data or not card['latest_suggested']:
            no_history.append(card)
            continue
        
        # Compare prices
        old_price = float(old_price_data['suggested_price_cad'])
        new_price = float(card['latest_suggested'])
        price_diff = new_price - old_price
        price_diff_percent = (price_diff / old_price * 100) if old_price > 0 else 0
        
        # Check if significant
        is_significant = (
            abs(price_diff_percent) >= SIGNIFICANT_CHANGE_PERCENT or
            abs(price_diff) >= SIGNIFICANT_CHANGE_AMOUNT
        )
        
        if not is_significant:
            no_changes.append(card)
            continue
        
        # Create change record
        change_record = {
            **card,
            'old_price': old_price,
            'new_price': new_price,
            'price_diff': price_diff,
            'price_diff_percent': price_diff_percent,
            'old_check_date': old_price_data['checked_at']
        }
        
        if price_diff < 0:
            price_drops.append(change_record)
        else:
            price_increases.append(change_record)
    
    print()
    print(f"✅ Analysis complete!")
    print(f"  • Price drops: {len(price_drops)}")
    print(f"  • Price increases: {len(price_increases)}")
    print(f"  • No significant changes: {len(no_changes)}")
    print(f"  • No price history: {len(no_history)}")
    print()
    
    return {
        'price_drops': sorted(price_drops, key=lambda x: x['price_diff']),
        'price_increases': sorted(price_increases, key=lambda x: x['price_diff'], reverse=True),
        'no_changes': no_changes,
        'no_history': no_history,
        'total_checked': len(cards),
        'comparison_date': seven_days_ago
    }


def generate_text_report(changes):
    """Generate text report"""
    report_date = datetime.now().strftime("%B %d, %Y")
    comparison_date = changes['comparison_date'].strftime("%B %d, %Y")
    
    report = f"""
╔══════════════════════════════════════════════════════════════════════╗
║          DUMPLING COLLECTIBLES - WEEKLY PRICE REPORT                 ║
║                  {report_date:^46}                 ║
╚══════════════════════════════════════════════════════════════════════╝

📊 SUMMARY
────────────────────────────────────────────────────────────────────────
• Comparison: {comparison_date} → {report_date}
• Total cards checked: {changes['total_checked']}
• Cards with price changes: {len(changes['price_drops']) + len(changes['price_increases'])}
  └─ Price drops: {len(changes['price_drops'])}
  └─ Price increases: {len(changes['price_increases'])}
• No significant changes: {len(changes['no_changes'])}


"""
    
    # Calculate impact
    total_drop_value = sum(c['price_diff'] * c['inventory_qty'] for c in changes['price_drops'])
    total_increase_value = sum(c['price_diff'] * c['inventory_qty'] for c in changes['price_increases'])
    net_change = total_increase_value + total_drop_value
    
    report += f"""💰 INVENTORY VALUE IMPACT
────────────────────────────────────────────────────────────────────────
• Price drops impact: ${total_drop_value:.2f}
• Price increases impact: +${total_increase_value:.2f}
• Net inventory change: {'' if net_change < 0 else '+'} ${net_change:.2f}


"""
    
    # Price Drops
    if changes['price_drops']:
        report += f"""
🔴 PRICE DROPS - NEED TO LOWER PRICES ({len(changes['price_drops'])} cards)
────────────────────────────────────────────────────────────────────────

"""
        for i, card in enumerate(changes['price_drops'][:20], 1):
            shopify_status = ""
            if card['current_shopify_price']:
                shopify_diff = float(card['current_shopify_price']) - card['new_price']
                if abs(shopify_diff) > 1.0:
                    shopify_status = f"\n   Your Shopify: ${float(card['current_shopify_price']):.2f} ⚠️ (${shopify_diff:+.2f} vs market)"
            
            report += f"""{i}. {card['card_name']} ({card['set_code']}-{card['number']}) - {card['condition']}
   Last week: ${card['old_price']:.2f} → This week: ${card['new_price']:.2f}
   Change: −${abs(card['price_diff']):.2f} ({abs(card['price_diff_percent']):.1f}%){shopify_status}
   On Hand: {card['inventory_qty']} card{'s' if card['inventory_qty'] > 1 else ''}
   Impact: −${abs(card['price_diff'] * card['inventory_qty']):.2f}

"""
        
        if len(changes['price_drops']) > 20:
            report += f"\n   ... and {len(changes['price_drops']) - 20} more\n"
    
    # Price Increases
    if changes['price_increases']:
        report += f"""

🟢 PRICE INCREASES - CAN RAISE PRICES ({len(changes['price_increases'])} cards)
────────────────────────────────────────────────────────────────────────

"""
        for i, card in enumerate(changes['price_increases'][:20], 1):
            shopify_status = ""
            if card['current_shopify_price']:
                shopify_diff = float(card['current_shopify_price']) - card['new_price']
                if abs(shopify_diff) > 1.0:
                    shopify_status = f"\n   Your Shopify: ${float(card['current_shopify_price']):.2f} ⚠️ (${shopify_diff:+.2f} vs market)"
            
            report += f"""{i}. {card['card_name']} ({card['set_code']}-{card['number']}) - {card['condition']}
   Last week: ${card['old_price']:.2f} → This week: ${card['new_price']:.2f}
   Change: +${card['price_diff']:.2f} (+{card['price_diff_percent']:.1f}%){shopify_status}
   On Hand: {card['inventory_qty']} card{'s' if card['inventory_qty'] > 1 else ''}
   Impact: +${card['price_diff'] * card['inventory_qty']:.2f}

"""
        
        if len(changes['price_increases']) > 20:
            report += f"\n   ... and {len(changes['price_increases']) - 20} more\n"
    
    if not changes['price_drops'] and not changes['price_increases']:
        report += """
✅ NO SIGNIFICANT PRICE CHANGES

All your cards are priced well! No action needed this week.

"""
    
    report += f"""
────────────────────────────────────────────────────────────────────────

📝 NOTES:
• Only showing changes of 5%+ or $2+ (to reduce noise)
• Prices based on TCGPlayer market data
• Your Shopify prices shown for comparison
• Consider local market conditions before updating

🎯 ACTION ITEMS:
1. Focus on price drops first (avoid overpricing)
2. Update Shopify prices for significant changes
3. Consider raising prices on cards with big increases

────────────────────────────────────────────────────────────────────────
Generated: {datetime.now().strftime("%Y-%m-%d %I:%M %p")}
"""
    
    return report


def generate_html_report(changes):
    """Generate HTML report for email"""
    # Similar structure to text report but with HTML formatting
    # (Code omitted for brevity - same structure as previous version)
    return generate_text_report(changes)  # Simplified for now


def main():
    """Main execution"""
    print("="*70)
    print("📊 WEEKLY PRICE CHANGE REPORT")
    print("="*70)
    print()
    
    # Calculate changes
    changes = calculate_price_changes()
    
    # Generate reports
    text_report = generate_text_report(changes)
    html_report = generate_html_report(changes)
    
    # Save reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    text_filename = f"price_report_{timestamp}.txt"
    with open(text_filename, 'w', encoding='utf-8') as f:
        f.write(text_report)
    print(f"📄 Report saved: {text_filename}")
    
    # Print to console
    print()
    print(text_report)
    
    return {
        'text_report': text_report,
        'html_report': html_report,
        'changes': changes,
        'text_filename': text_filename
    }


if __name__ == "__main__":
    main()
