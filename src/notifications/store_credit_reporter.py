import requests
from src.config import config

class StoreCreditReporter:
    """
    Dedicated notifications logic for the Store Credit domain.
    Builds and delivers HTML gift card codes and balance updates to 
    customers via Brevo's REST API.
    """

    @staticmethod
    def _send_brevo_email(subject, html_content, to_email):
        if not config.BREVO_API_KEY:
            return False
            
        email_payload = {
            "sender": {"name": config.FROM_NAME, "email": config.EMAIL_FROM},
            "to": [{"email": to_email}],
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

    def send_gift_card_notification(self, customer_email, gift_card_code, amount, reason=None, balance_after=None):
        """Builds and sends the gift card email receipt to the customer."""
        subject = f"🎁 Store Credit Issued - ${amount:.2f}"
        
        reason_html = f'<p style="color: #666; font-size: 14px; margin: 10px 0;"><em>{reason}</em></p>' if reason else ""
        
        balance_html = ""
        if balance_after is not None:
            balance_html = f'''
            <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <p style="margin: 0; font-size: 14px; color: #1976d2;">
                    💰 <strong>Your Total Store Credit Balance:</strong> ${balance_after:.2f}
                </p>
            </div>'''

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px;">
                    <h1 style="margin: 0;">🎁 Store Credit Issued!</h1>
                </div>
                
                <div style="padding: 20px;">
                    <p style="font-size: 18px;">Great news!</p>
                    <p>You've received <strong>${amount:.2f}</strong> in store credit at {config.STORE_NAME}!</p>
                    {reason_html}
                    
                    <div style="background: #f8f9fa; padding: 30px; margin: 20px 0; text-align: center; border-radius: 10px; border: 2px dashed #667eea;">
                        <p style="margin: 0 0 10px 0; color: #666;">Your Gift Card Code:</p>
                        <div style="font-size: 24px; font-weight: bold; color: #667eea; letter-spacing: 2px; padding: 15px; background: white; border-radius: 5px;">
                            {gift_card_code}
                        </div>
                        <p style="margin: 15px 0 0 0; font-size: 14px; color: #666;">Use this code at checkout to redeem your credit</p>
                    </div>
                    {balance_html}
                </div>
            </div>
        </body>
        </html>"""
        
        return self._send_brevo_email(subject, html, customer_email)
