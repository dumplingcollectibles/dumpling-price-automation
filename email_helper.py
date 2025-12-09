"""
Email Helper - Brevo (Sendinblue) Version with Internal Notifications

Handles all email sending via Brevo (formerly Sendinblue).
Actually free forever - 300 emails/day (9,000/month)!

Usage:
  from email_helper import send_gift_card_email, send_buylist_confirmation_email, send_internal_buylist_notification
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv('BREVO_API_KEY')
FROM_EMAIL = os.getenv('EMAIL_FROM', 'admin@dumplingcollectibles.com')
FROM_NAME = os.getenv('FROM_NAME', 'Dumpling Collectibles')
STORE_NAME = os.getenv('STORE_NAME', 'Dumpling Collectibles')
STORE_URL = os.getenv('STORE_URL', 'https://dumplingcollectibles.com')
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL', 'buylist@dumplingcollectibles.com')


def send_email(to_email, subject, html_content, to_name=None):
    """
    Send email via Brevo API
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML body content
        to_name: Optional recipient name
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not BREVO_API_KEY:
        print("⚠️  Brevo not configured - email not sent")
        print(f"   (Would have sent to: {to_email})")
        return False
    
    url = "https://api.brevo.com/v3/smtp/email"
    
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {
            "name": FROM_NAME,
            "email": FROM_EMAIL
        },
        "to": [
            {
                "email": to_email,
                "name": to_name or to_email
            }
        ],
        "subject": subject,
        "htmlContent": html_content
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"❌ Brevo API error: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False


def send_gift_card_email(customer_email, gift_card_code, amount, reason=None, balance_after=None):
    """
    Send gift card email to customer
    
    Args:
        customer_email: Customer's email address
        gift_card_code: Shopify gift card code
        amount: Gift card amount
        reason: Optional reason text (e.g., "Buylist Payment - Quote #123")
        balance_after: Optional store credit balance after this transaction
    """
    
    subject = f"🎁 Store Credit Issued - ${amount:.2f}"
    
    reason_html = ""
    if reason:
        reason_html = f'<p style="color: #666; font-size: 14px; margin: 10px 0;"><em>{reason}</em></p>'
    
    balance_html = ""
    if balance_after is not None:
        balance_html = f'''
        <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <p style="margin: 0; font-size: 14px; color: #1976d2;">
                💰 <strong>Your Total Store Credit Balance:</strong> ${balance_after:.2f}
            </p>
        </div>
        '''
    
    html_content = f'''
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                      color: white; padding: 30px; text-align: center; border-radius: 10px; }}
            .gift-card {{ background: #f8f9fa; padding: 30px; margin: 20px 0; text-align: center; 
                         border-radius: 10px; border: 2px dashed #667eea; }}
            .code {{ font-size: 24px; font-weight: bold; color: #667eea; letter-spacing: 2px; 
                    padding: 15px; background: white; border-radius: 5px; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; 
                      padding-top: 20px; border-top: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0;">🎁 Store Credit Issued!</h1>
            </div>
            
            <div style="padding: 20px;">
                <p style="font-size: 18px;">Great news!</p>
                
                <p>You've received <strong>${amount:.2f}</strong> in store credit at {STORE_NAME}!</p>
                
                {reason_html}
                
                <div class="gift-card">
                    <p style="margin: 0 0 10px 0; color: #666;">Your Gift Card Code:</p>
                    <div class="code">{gift_card_code}</div>
                    <p style="margin: 15px 0 0 0; font-size: 14px; color: #666;">
                        Use this code at checkout to redeem your credit
                    </p>
                </div>
                
                {balance_html}
                
                <p style="margin-top: 30px;">
                    <a href="{STORE_URL}" style="display: inline-block; padding: 15px 30px; 
                       background: #667eea; color: white; text-decoration: none; border-radius: 5px; 
                       font-weight: bold;">Start Shopping →</a>
                </p>
                
                <p style="margin-top: 20px; font-size: 14px; color: #666;">
                    Questions? Reply to this email or visit our store.
                </p>
            </div>
            
            <div class="footer">
                <p>{STORE_NAME}<br>
                This email was sent because store credit was issued to your account.</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    success = send_email(customer_email, subject, html_content)
    return success


def send_buylist_confirmation_email(customer_email, customer_name, buy_offer_id, 
                                    quoted_total, payout_method, items, expires_at):
    """
    Send buylist submission confirmation to customer
    
    Args:
        customer_email: Customer's email
        customer_name: Customer's name (optional)
        buy_offer_id: Quote ID
        quoted_total: Total quote amount
        payout_method: 'cash' or 'credit'
        items: List of items with card details
        expires_at: Quote expiration datetime
    """
    
    greeting = f"Hi {customer_name}!" if customer_name else "Hi there!"
    payout_text = "cash" if payout_method == "cash" else "store credit"
    
    subject = f"📝 Buylist Quote Received - ${quoted_total:.2f}"
    
    # Build items HTML
    items_html = ""
    for item in items:
        items_html += f'''
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">
                <strong>{item['card_name']}</strong><br>
                <span style="color: #666; font-size: 14px;">{item['set_name']} #{item['number']}</span>
            </td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">
                {item['condition']}
            </td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">
                {item['quantity']}
            </td>
            <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">
                ${item['item_total']:.2f}
            </td>
        </tr>
        '''
    
    html_content = f'''
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                      color: white; padding: 30px; text-align: center; border-radius: 10px; }}
            .quote-box {{ background: #f8f9fa; padding: 20px; margin: 20px 0; 
                         border-radius: 10px; border-left: 4px solid #667eea; }}
            .timeline {{ background: #fff; padding: 20px; margin: 20px 0; }}
            .timeline-step {{ display: flex; margin: 15px 0; }}
            .step-number {{ background: #667eea; color: white; width: 30px; height: 30px; 
                           border-radius: 50%; display: flex; align-items: center; 
                           justify-content: center; font-weight: bold; margin-right: 15px; 
                           flex-shrink: 0; }}
            table {{ width: 100%; border-collapse: collapse; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; 
                      padding-top: 20px; border-top: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0;">✅ Quote Received!</h1>
            </div>
            
            <div style="padding: 20px;">
                <p style="font-size: 18px;">{greeting}</p>
                
                <p>Thanks for your buylist submission! We've received your request and will review it within 24 hours.</p>
                
                <div class="quote-box">
                    <h3 style="margin-top: 0;">📋 Quote Summary</h3>
                    <p><strong>Quote ID:</strong> #{buy_offer_id}</p>
                    <p><strong>Total Offer:</strong> ${quoted_total:.2f} ({payout_text})</p>
                    <p><strong>Valid Until:</strong> {expires_at.strftime('%B %d, %Y')}</p>
                </div>
                
                <h3>📦 Your Cards:</h3>
                <table>
                    <thead>
                        <tr style="background: #f8f9fa;">
                            <th style="padding: 10px; text-align: left;">Card</th>
                            <th style="padding: 10px; text-align: center;">Condition</th>
                            <th style="padding: 10px; text-align: center;">Qty</th>
                            <th style="padding: 10px; text-align: right;">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                    <tfoot>
                        <tr style="background: #f8f9fa; font-weight: bold;">
                            <td colspan="3" style="padding: 15px; text-align: right;">Total:</td>
                            <td style="padding: 15px; text-align: right; color: #667eea; font-size: 18px;">
                                ${quoted_total:.2f}
                            </td>
                        </tr>
                    </tfoot>
                </table>
                
                <div class="timeline">
                    <h3>📅 What's Next?</h3>
                    <div class="timeline-step">
                        <div class="step-number">1</div>
                        <div>
                            <strong>We'll Review Your Quote</strong><br>
                            <span style="color: #666; font-size: 14px;">Within 24 hours, we'll email you our decision</span>
                        </div>
                    </div>
                    <div class="timeline-step">
                        <div class="step-number">2</div>
                        <div>
                            <strong>Ship Your Cards</strong><br>
                            <span style="color: #666; font-size: 14px;">If approved, we'll send shipping instructions</span>
                        </div>
                    </div>
                    <div class="timeline-step">
                        <div class="step-number">3</div>
                        <div>
                            <strong>Get Paid!</strong><br>
                            <span style="color: #666; font-size: 14px;">Once received and verified, you'll get your {payout_text}</span>
                        </div>
                    </div>
                </div>
                
                <p style="margin-top: 30px; padding: 15px; background: #fff3cd; border-radius: 5px; border-left: 4px solid #ffc107;">
                    ⚠️ <strong>Important:</strong> This quote expires on {expires_at.strftime('%B %d, %Y')}. 
                    Please respond before this date if you'd like to proceed.
                </p>
                
                <p style="margin-top: 20px;">
                    Questions? Just reply to this email!
                </p>
            </div>
            
            <div class="footer">
                <p>{STORE_NAME}<br>
                Thank you for choosing us to buy your cards!</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    success = send_email(customer_email, subject, html_content, to_name=customer_name)
    return success


def send_internal_buylist_notification(buy_offer_id, customer_email, customer_name, 
                                       quoted_total, payout_method, items, item_count):
    """
    Send internal notification to store staff when new buylist is submitted
    
    Args:
        buy_offer_id: Quote ID
        customer_email: Customer's email
        customer_name: Customer's name (optional)
        quoted_total: Total quote amount
        payout_method: 'cash' or 'credit'
        items: List of items with card details
        item_count: Total number of cards
    """
    
    customer_display = f"{customer_name} ({customer_email})" if customer_name else customer_email
    payout_text = "Cash" if payout_method == "cash" else "Store Credit"
    
    subject = f"🔔 New Buylist #{buy_offer_id} - ${quoted_total:.2f}"
    
    # Build items HTML
    items_html = ""
    for item in items:
        items_html += f'''
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #eee; font-size: 14px;">
                <strong>{item['card_name']}</strong><br>
                <span style="color: #666; font-size: 12px;">{item['set_name']} #{item['number']}</span>
            </td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center; font-size: 14px;">
                {item['condition']}
            </td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center; font-size: 14px;">
                {item['quantity']}
            </td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right; font-size: 14px;">
                ${item['item_total']:.2f}
            </td>
        </tr>
        '''
    
    html_content = f'''
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #1976d2; color: white; padding: 20px; border-radius: 10px; }}
            .alert-box {{ background: #fff3cd; padding: 15px; margin: 20px 0; 
                         border-radius: 5px; border-left: 4px solid #ffc107; }}
            .info-box {{ background: #f8f9fa; padding: 15px; margin: 20px 0; border-radius: 5px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            .action-btn {{ display: inline-block; padding: 12px 24px; background: #1976d2; 
                          color: white; text-decoration: none; border-radius: 5px; 
                          font-weight: bold; margin: 10px 5px; }}
            .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; 
                      padding-top: 20px; border-top: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">🔔 New Buylist Submission</h2>
                <p style="margin: 10px 0 0 0; font-size: 16px;">Quote #{buy_offer_id}</p>
            </div>
            
            <div class="alert-box">
                <strong>⚡ Action Required:</strong> New buylist submission needs review
            </div>
            
            <div class="info-box">
                <h3 style="margin-top: 0;">📊 Quick Summary</h3>
                <p style="margin: 5px 0;"><strong>Quote ID:</strong> #{buy_offer_id}</p>
                <p style="margin: 5px 0;"><strong>Customer:</strong> {customer_display}</p>
                <p style="margin: 5px 0;"><strong>Total Offer:</strong> ${quoted_total:.2f} ({payout_text})</p>
                <p style="margin: 5px 0;"><strong>Card Count:</strong> {item_count} card(s)</p>
            </div>
            
            <h3>📦 Cards in Buylist:</h3>
            <table>
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 10px; text-align: left; font-size: 14px;">Card</th>
                        <th style="padding: 10px; text-align: center; font-size: 14px;">Condition</th>
                        <th style="padding: 10px; text-align: center; font-size: 14px;">Qty</th>
                        <th style="padding: 10px; text-align: right; font-size: 14px;">Total</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
                <tfoot>
                    <tr style="background: #f8f9fa; font-weight: bold;">
                        <td colspan="3" style="padding: 12px; text-align: right; font-size: 16px;">Total:</td>
                        <td style="padding: 12px; text-align: right; color: #1976d2; font-size: 18px;">
                            ${quoted_total:.2f}
                        </td>
                    </tr>
                </tfoot>
            </table>
            
            <div style="margin: 30px 0; padding: 20px; background: #e3f2fd; border-radius: 10px;">
                <h3 style="margin-top: 0; color: #1976d2;">👉 Next Steps:</h3>
                <ol style="margin: 10px 0; padding-left: 20px;">
                    <li style="margin: 8px 0;">Review the cards and pricing</li>
                    <li style="margin: 8px 0;">Run <code style="background: white; padding: 2px 6px; border-radius: 3px;">approve_buylist.py</code> to approve</li>
                    <li style="margin: 8px 0;">Or contact customer if adjustments needed</li>
                </ol>
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <p style="color: #666; font-size: 14px;">Use your admin scripts to manage this buylist</p>
            </div>
            
            <div class="footer">
                <p>Internal notification from {STORE_NAME} Buylist System<br>
                This email was sent to: {NOTIFICATION_EMAIL}</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    success = send_email(NOTIFICATION_EMAIL, subject, html_content, to_name="Buylist Team")
    return success


if __name__ == "__main__":
    print("Email helper loaded successfully")
    print(f"Notification emails will be sent to: {NOTIFICATION_EMAIL}")
