"""
Send Weekly Price Report Email
Wrapper script for GitHub Actions

Usage:
    python send_report_email.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_price_report import main as generate_report
from email_sender import send_email_report


def main():
    """Generate and send price report"""
    print("="*70)
    print("📊 WEEKLY PRICE REPORT - EMAIL SENDER")
    print("="*70)
    print()
    
    # Generate report
    result = generate_report()
    
    if not result:
        print("\n❌ Failed to generate report")
        return False
    
    # Send email
    print("\n" + "="*70)
    print("📧 SENDING EMAIL")
    print("="*70)
    print()
    
    success = send_email_report(
        result['html_report'],
        result['text_report'],
        result['changes']
    )
    
    if success:
        print("\n✅ Report sent successfully!")
        return True
    else:
        print("\n❌ Failed to send report")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
