import requests
from datetime import datetime
from src.config import config
from src.buylist.buylist_config import buylist_config

class BuylistReporter:
    """
    Dedicated notifications logic for the Buylist domain.
    Builds and delivers HTML email quotes to customers and staff using 
    Brevo's REST API.
    """

    @staticmethod
    def _send_brevo_email(subject, html_content, to_email, to_name):
        if not config.BREVO_API_KEY:
            return False
            
        email_payload = {
            "sender": {"name": config.FROM_NAME, "email": config.EMAIL_FROM},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content
        }
        
        try:
            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "accept": "application/json",
                    "api-key": config.BREVO_API_KEY,
                    "content-type": "application/json"
                },
                json=email_payload,
                timeout=10
            )
            return response.status_code == 201
        except Exception:
            return False

    def send_customer_confirmation(self, data):
        """Send quote confirmation email to the user."""
        items_html = ""
        for item in data['items']:
            items_html += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{item['card_name']}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{item['set_name']}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{item['condition']}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{item['quantity']}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right;">${item['price_per_unit']:.2f}</td>
            </tr>"""

        subject = buylist_config.SUBJECT_CUSTOMER_CONFIRMATION.format(store_name=config.STORE_NAME)
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; text-align: center;">
                    <h1>✅ Quote Received!</h1>
                </div>
                <div style="padding: 30px; background: #f9f9f9;">
                    <p>Hi {data['customer_name'] or 'there'},</p>
                    <p>We've received your submission for <strong>Quote #{data['quote_id']}</strong>.</p>
                    
                    <div style="background: white; padding: 20px; border-left: 4px solid #667eea; margin: 20px 0;">
                        <p><strong>Payment Method:</strong> {data['payout_method'].upper()}</p>
                        <p><strong>Expires:</strong> {data['expires_at'].strftime('%B %d, %Y')}</p>
                    </div>

                    <div style="background: #667eea; color: white; padding: 15px; text-align: center; font-size: 1.25em; border-radius: 8px;">
                        <strong>Total: ${data['total']:.2f} CAD</strong>
                    </div>

                    <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                        <thead style="background: #eee;">
                            <tr><th style="padding: 8px;">Card</th><th style="padding: 8px;">Set</th><th style="padding: 8px;">Cond</th><th style="padding: 8px;">Qty</th><th style="padding: 8px;">Price</th></tr>
                        </thead>
                        <tbody>{items_html}</tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>"""
        
        return self._send_brevo_email(subject, html, data['customer_email'], data['customer_name'] or "Valued Customer")

    def send_internal_notification(self, data):
        """Send submission notification to the store staff."""
        items_html = ""
        for item in data['items']:
            items_html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{item['card_name']}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item['set_name']}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item['condition']}</td>
                <td style="padding: 8px; border: 1px solid #ddd;">{item['quantity']}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${item['item_total']:.2f}</td>
            </tr>"""

        subject = buylist_config.SUBJECT_INTERNAL_NOTIFICATION.format(quote_id=data['quote_id'])
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background: #f4f4f4; padding: 20px;">
                <h2>🔔 New Buylist #{data['quote_id']}</h2>
                <p><strong>Customer:</strong> {data['customer_name'] or 'N/A'} ({data['customer_email']})</p>
                <p><strong>Payout:</strong> {data['payout_method'].upper()}</p>
                <p><strong>Total: ${data['total']:.2f} CAD</strong></p>
                
                <table style="width: 100%; border-collapse: collapse; background: white; margin-top: 20px;">
                    <thead style="background: #667eea; color: white;">
                        <tr><th style="padding: 10px;">Card</th><th style="padding: 10px;">Set</th><th style="padding: 10px;">Cond</th><th style="padding: 10px;">Qty</th><th style="padding: 10px;">Total</th></tr>
                    </thead>
                    <tbody>{items_html}</tbody>
                </table>
            </div>
        </body>
        </html>"""
        
        return self._send_brevo_email(subject, html, buylist_config.INTERNAL_CONTACT_EMAIL, "Buylist Team")
