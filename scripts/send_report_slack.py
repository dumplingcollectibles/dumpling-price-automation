"""
Send Weekly Price Report to Slack
Wrapper script for GitHub Actions

Usage:
    python send_report_slack.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_price_report import main as generate_report
from slack_sender import send_slack_report


def main():
    """Generate and send price report to Slack"""
    print("="*70)
    print("📊 WEEKLY PRICE REPORT - SLACK SENDER")
    print("="*70)
    print()
    
    # Generate report
    result = generate_report()
    
    if not result:
        print("\n❌ Failed to generate report")
        return False
    
    # Send to Slack
    print("\n" + "="*70)
    print("📤 SENDING TO SLACK")
    print("="*70)
    print()
    
    success = send_slack_report(
        result['text_report'],
        result['changes']
    )
    
    if success:
        print("\n✅ Report sent to Slack successfully!")
        return True
    else:
        print("\n❌ Failed to send report to Slack")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
