"""
Price History Job Controller
CLI wrapper for snapshotting current store prices into the historical database 
and calculating rolling weekly deltas.

Usage:
  python -m src.pricing_engine.price_history_job snapshot
  python -m src.pricing_engine.price_history_job weekly
"""
import sys
import argparse
from datetime import datetime
from src.pricing_engine.price_history_service import PriceHistoryService
from src.notifications.pricing_reporter import PricingReporter

def generate_text_report(changes):
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
    total_drop = sum(c['price_diff'] * c['inventory_qty'] for c in changes['price_drops'])
    total_inc = sum(c['price_diff'] * c['inventory_qty'] for c in changes['price_increases'])
    net = total_inc + total_drop
    
    report += f"""
💰 INVENTORY VALUE IMPACT
────────────────────────────────────────────────────────────────────────
• Price drops impact: ${total_drop:.2f}
• Price increases impact: +${total_inc:.2f}
• Net inventory change: {'' if net < 0 else '+'}${net:.2f}
"""

    if changes['price_drops']:
        report += f"\n🔴 PRICE DROPS - NEED TO LOWER PRICES ({len(changes['price_drops'])} cards)\n" + "─"*72 + "\n"
        for i, card in enumerate(changes['price_drops'][:20], 1):
            sp_diff = ""
            if card['current_shopify_price']:
                diff = float(card['current_shopify_price']) - card['new_price']
                if abs(diff) > 1.0: sp_diff = f"\n   Your Shopify: ${float(card['current_shopify_price']):.2f} ⚠️ (${diff:+.2f} vs market)"
            report += f"{i}. {card['card_name']} ({card['set_code']}-{card['number']}) - {card['condition']}\n   Last week: ${card['old_price']:.2f} → This week: ${card['new_price']:.2f}\n   Change: −${abs(card['price_diff']):.2f} ({abs(card['price_diff_percent']):.1f}%){sp_diff}\n   On Hand: {card['inventory_qty']} cards\n"

    if changes['price_increases']:
        report += f"\n🟢 PRICE INCREASES - CAN RAISE PRICES ({len(changes['price_increases'])} cards)\n" + "─"*72 + "\n"
        for i, card in enumerate(changes['price_increases'][:20], 1):
            sp_diff = ""
            if card['current_shopify_price']:
                diff = float(card['current_shopify_price']) - card['new_price']
                if abs(diff) > 1.0: sp_diff = f"\n   Your Shopify: ${float(card['current_shopify_price']):.2f} ⚠️ (${diff:+.2f} vs market)"
            report += f"{i}. {card['card_name']} ({card['set_code']}-{card['number']}) - {card['condition']}\n   Last week: ${card['old_price']:.2f} → This week: ${card['new_price']:.2f}\n   Change: +${card['price_diff']:.2f} ({card['price_diff_percent']:.1f}%){sp_diff}\n   On Hand: {card['inventory_qty']} cards\n"

    return report


def main():
    parser = argparse.ArgumentParser(description='Price History Job Controller')
    subparsers = parser.add_subparsers(dest='mode', required=True)
    subparsers.add_parser('snapshot', help='Log current DB prices to price_history table')
    subparsers.add_parser('weekly', help='Compare last 7 days metrics and print report')
    
    args = parser.parse_args()
    service = PriceHistoryService()

    if args.mode == 'snapshot':
        print("="*70)
        print("📊 DAILY PRICE TRACKER (Snapshot mode)")
        print("="*70)
        res = service.snapshot_daily_prices()
        print(f"✅ Success! Tracked {res['tracked']} new variants, updated {res['updated']}.")
        if res['errors']:
            print(f"⚠️ Recovered from {res['errors']} missing IDs.")

    elif args.mode == 'weekly':
        print("="*70)
        print("📊 WEEKLY PRICE CHANGE REPORT")
        print("="*70)
        changes = service.calculate_weekly_changes()
        report_str = generate_text_report(changes)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"price_report_{timestamp}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report_str)
            
        print(report_str)
        print(f"📄 Full report saved: {filename}")
        
if __name__ == "__main__":
    main()
