"""
Email Sender for Price Reports
Dumpling Collectibles

Sends HTML email reports via Gmail SMTP or SendGrid
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Email configuration
EMAIL_FROM = os.getenv('EMAIL_FROM')  # Your email
EMAIL_TO = os.getenv('EMAIL_TO')  # Where to send report (can be same)
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')  # App password
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))


def send_email_report(html_content, text_content, changes_summary):
    """
    Send email report
    
    Args:
        html_content: HTML formatted report
        text_content: Plain text fallback
        changes_summary: Dict with summary stats
    """
    
    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_PASSWORD:
        print("❌ Email credentials not configured!")
        print("   Set EMAIL_FROM, EMAIL_TO, and EMAIL_PASSWORD in .env")
        return False
    
    # Create subject line
    total_changes = len(changes_summary['price_drops']) + len(changes_summary['price_increases'])
    date_str = datetime.now().strftime("%b %d, %Y")
    
    if total_changes == 0:
        subject = f"✅ No Price Changes - {date_str}"
    else:
        subject = f"📊 {total_changes} Price Changes for Weekend Show - {date_str}"
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    
    # Attach both versions
    text_part = MIMEText(text_content, 'plain', 'utf-8')
    html_part = MIMEText(html_content, 'html', 'utf-8')
    
    msg.attach(text_part)
    msg.attach(html_part)
    
    # Send email
    try:
        print(f"📧 Sending email to {EMAIL_TO}...")
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send email: {str(e)}")
        return False


if __name__ == "__main__":
    # Test email
    test_html = "<h1>Test Email</h1><p>If you see this, email is working!</p>"
    test_text = "Test Email\n\nIf you see this, email is working!"
    test_summary = {'price_drops': [], 'price_increases': []}
    
    send_email_report(test_html, test_text, test_summary)
