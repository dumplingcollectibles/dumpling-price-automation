"""
Email Helper - Brevo (Sendinblue) Version

Handles all email sending via Brevo API.
FREE FOREVER: 300 emails/day (9,000/month)

Usage:
  from email_helper import send_gift_card_email, send_buylist_confirmation_email
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
    Send gift card issued email to customer
    
    Args:
        customer_email: Customer's email
        gift_card_code: The gift card code
        amount: Amount issued
        reason: Optional reason (e.g., "Buylist payment")
        balance_after: Optional total balance after this
    """
    
    subject = f"🎁 Store Credit Issued - ${amount:.2f}"
    
    reason_html = ""
    if reason:
        reason_html = f'<p style="color: #666; font-style: italic;">Reason: {reason}</p>'
    
    balance_html = ""
    if balance_after:
        balance_html = f'''
        <div style="background: #e8f5e9; padding: 15px; margin: 20px 0; border-radius: 5px;">
            <strong>Your Total Store Credit Balance: ${balance_after:.2f}</strong>
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
            .code-box {{ background: #f8f9fa; border: 2px dashed #667eea; 
                        padding: 20px; margin: 20px 0; text-align: center; border-radius: 10px; }}
            .code {{ font-size: 28px; font-weight: bold; color: #667eea; 
                    letter-spacing: 2px; font-family: monospace; }}
            .steps {{ background: #fff; padding: 20px; border-left: 4px solid #667eea; }}
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
                <p style="font-size: 18px;">Great news! You've received <strong>${amount:.2f}</strong> in store credit!</p>
                
                {reason_html}
                
                <div class="code-box">
                    <p style="margin: 0 0 10px 0; font-size: 14px; color: #666;">YOUR GIFT CARD CODE:</p>
                    <div class="code">{gift_card_code}</div>
                </div>
                
                {balance_html}
                
                <div class="steps">
                    <h3 style="margin-top: 0;">How to Use Your Store Credit:</h3>
                    <ol style="padding-left: 20px;">
                        <li>Shop at <a href="{STORE_URL}" style="color: #667eea;">{STORE_URL}</a></li>
                        <li>Add items to your cart</li>
                        <li>At checkout, enter your gift card code</li>
                        <li>Your discount will be applied automatically!</li>
                    </ol>
                </div>
                
                <div style="background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <strong>💡 Pro Tip:</strong> Save this email! You can use your gift card code anytime.
                </div>
                
                <p>Questions? Just reply to this email - we're here to help!</p>
                
                <p style="margin-top: 30px;">
                    Happy shopping!<br>
                    <strong>- The {STORE_NAME} Team</strong>
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
                    <p style="margin: 5px 0;"><strong>Quote ID:</strong> #{buy_offer_id}</p>
                    <p style="margin: 5px 0;"><strong>Total:</strong> ${quoted_total:.2f} ({payout_text})</p>
                    <p style="margin: 5px 0;"><strong>Items:</strong> {len(items)} card{'s' if len(items) > 1 else ''}</p>
                    <p style="margin: 5px 0;"><strong>Expires:</strong> {expires_at.strftime('%B %d, %Y')}</p>
                </div>
                
                <h3>📦 Cards You're Selling:</h3>
                <table style="background: white; margin: 10px 0;">
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
                            <td colspan="3" style="padding: 10px; text-align: right;">TOTAL:</td>
                            <td style="padding: 10px; text-align: right;">${quoted_total:.2f}</td>
                        </tr>
                    </tfoot>
                </table>
                
                <div class="timeline">
                    <h3 style="margin-top: 0;">📅 What Happens Next:</h3>
                    
                    <div class="timeline-step">
                        <div class="step-number">1</div>
                        <div>
                            <strong>Review (Within 24 hours)</strong><br>
                            We'll review your submission and verify prices.
                        </div>
                    </div>
                    
                    <div class="timeline-step">
                        <div class="step-number">2</div>
                        <div>
                            <strong>Approval Email</strong><br>
                            You'll receive shipping instructions if approved.
                        </div>
                    </div>
                    
                    <div class="timeline-step">
                        <div class="step-number">3</div>
                        <div>
                            <strong>Ship Your Cards</strong><br>
                            Package securely and ship to our address.
                        </div>
                    </div>
                    
                    <div class="timeline-step">
                        <div class="step-number">4</div>
                        <div>
                            <strong>Get Paid!</strong><br>
                            Receive your {payout_text} within 24 hours of us receiving your cards.
                        </div>
                    </div>
                </div>
                
                <div style="background: #e3f2fd; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <strong>💡 Important:</strong> Cards must match the conditions you declared. 
                    If conditions don't match, we'll contact you before adjusting payment.
                </div>
                
                <div style="background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <strong>⏰ Quote Expires:</strong> {expires_at.strftime('%B %d, %Y')}<br>
                    <span style="font-size: 14px;">This gives us time to review your submission.</span>
                </div>
                
                <p>Questions? Just reply to this email - we're here to help!</p>
                
                <p style="margin-top: 30px;">
                    Thanks for choosing {STORE_NAME}!<br>
                    <strong>- The {STORE_NAME} Team</strong>
                </p>
            </div>
            
            <div class="footer">
                <p>{STORE_NAME}<br>
                Quote ID: #{buy_offer_id} | Submitted: {expires_at.strftime('%B %d, %Y')}</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    success = send_email(customer_email, subject, html_content, to_name=customer_name)
    return success
