"""
Slack Sender for Price Reports
Dumpling Collectibles

Sends price change reports to Slack channel
Much simpler than email!
"""

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Slack configuration
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')


def send_slack_report(text_content, changes_summary):
    """
    Send report to Slack
    
    Args:
        text_content: Plain text report
        changes_summary: Dict with summary stats
    """
    
    if not SLACK_WEBHOOK_URL:
        print("❌ SLACK_WEBHOOK_URL not configured!")
        print("   Get one at: https://api.slack.com/messaging/webhooks")
        return False
    
    # Create message
    total_changes = len(changes_summary['price_drops']) + len(changes_summary['price_increases'])
    date_str = datetime.now().strftime("%b %d, %Y")
    
    if total_changes == 0:
        title = f"✅ No Price Changes - {date_str}"
        color = "good"  # Green
    else:
        title = f"📊 {total_changes} Price Changes for Weekend Show - {date_str}"
        color = "warning"  # Orange/Yellow
    
    # Build summary section
    summary_text = f"""
*Summary:*
• Total cards checked: {changes_summary['total_checked']}
• Cards with changes: {total_changes}
  └─ Price drops: {len(changes_summary['price_drops'])} 🔴
  └─ Price increases: {len(changes_summary['price_increases'])} 🟢
"""
    
    # Build price drops section
    drops_text = ""
    if changes_summary['price_drops']:
        drops_text = "\n*🔴 PRICE DROPS - Need to Lower:*\n"
        for i, card in enumerate(changes_summary['price_drops'][:10], 1):
            drops_text += f"\n{i}. *{card['card_name']}* ({card['set_code']}-{card['number']}) - {card['condition']}\n"
            drops_text += f"   ${card['old_price']:.2f} → ${card['new_price']:.2f} "
            drops_text += f"(−${abs(card['price_diff']):.2f}, {abs(card['price_diff_percent']):.1f}%)\n"
            drops_text += f"   On hand: {card['inventory_qty']} card{'s' if card['inventory_qty'] > 1 else ''}"
        
        if len(changes_summary['price_drops']) > 10:
            drops_text += f"\n\n_... and {len(changes_summary['price_drops']) - 10} more price drops_"
    
    # Build price increases section
    increases_text = ""
    if changes_summary['price_increases']:
        increases_text = "\n*🟢 PRICE INCREASES - Can Raise:*\n"
        for i, card in enumerate(changes_summary['price_increases'][:10], 1):
            increases_text += f"\n{i}. *{card['card_name']}* ({card['set_code']}-{card['number']}) - {card['condition']}\n"
            increases_text += f"   ${card['old_price']:.2f} → ${card['new_price']:.2f} "
            increases_text += f"(+${card['price_diff']:.2f}, +{card['price_diff_percent']:.1f}%)\n"
            increases_text += f"   On hand: {card['inventory_qty']} card{'s' if card['inventory_qty'] > 1 else ''}"
        
        if len(changes_summary['price_increases']) > 10:
            increases_text += f"\n\n_... and {len(changes_summary['price_increases']) - 10} more price increases_"
    
    # No changes message
    if total_changes == 0:
        main_text = "\n✅ *All your cards are priced correctly!*\n\nNo action needed this week."
    else:
        main_text = summary_text + drops_text + increases_text
    
    # Calculate value impact
    total_drop_value = sum(c['price_diff'] * c['inventory_qty'] for c in changes_summary['price_drops'])
    total_increase_value = sum(c['price_diff'] * c['inventory_qty'] for c in changes_summary['price_increases'])
    net_change = total_increase_value + total_drop_value
    
    if total_changes > 0:
        impact_text = f"\n\n*💰 Inventory Value Impact:*\n"
        impact_text += f"• Price drops: ${total_drop_value:.2f}\n"
        impact_text += f"• Price increases: +${total_increase_value:.2f}\n"
        impact_text += f"• Net change: {'' if net_change < 0 else '+'} ${net_change:.2f}"
        main_text += impact_text
    
    # Create Slack message payload
    payload = {
        "username": "Price Report Bot",
        "icon_emoji": ":chart_with_upwards_trend:",
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": main_text,
                "footer": "Dumpling Collectibles Price Tracker",
                "footer_icon": "https://platform.slack-edge.com/img/default_application_icon.png",
                "ts": int(datetime.now().timestamp())
            }
        ]
    }
    
    # Send to Slack
    try:
        print(f"📤 Sending to Slack...")
        
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ Slack message sent successfully!")
            return True
        else:
            print(f"❌ Slack API error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to send Slack message: {str(e)}")
        return False


if __name__ == "__main__":
    # Test message
    print("="*70)
    print("📤 SLACK SENDER TEST")
    print("="*70)
    print()
    
    print(f"Configuration:")
    print(f"  SLACK_WEBHOOK_URL: {'✅ Set' if SLACK_WEBHOOK_URL else '❌ Not set'}")
    print()
    
    # Test with sample data
    test_summary = {
        'total_checked': 234,
        'price_drops': [
            {
                'card_name': 'Charizard ex',
                'set_code': 'sv03',
                'number': '125',
                'condition': 'NM',
                'old_price': 95.00,
                'new_price': 82.50,
                'price_diff': -12.50,
                'price_diff_percent': -13.2,
                'inventory_qty': 2
            }
        ],
        'price_increases': [
            {
                'card_name': 'Umbreon VMAX',
                'set_code': 'swsh7',
                'number': '095',
                'condition': 'NM',
                'old_price': 120.00,
                'new_price': 145.00,
                'price_diff': 25.00,
                'price_diff_percent': 20.8,
                'inventory_qty': 1
            }
        ],
        'no_changes': [],
        'no_history': []
    }
    
    test_text = "This is a test report"
    
    success = send_slack_report(test_text, test_summary)
    
    if success:
        print("\n🎉 Test successful! Check your Slack channel.")
    else:
        print("\n❌ Test failed. Check the error messages above.")
