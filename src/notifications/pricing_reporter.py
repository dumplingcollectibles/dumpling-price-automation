import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.config import config

class PricingReporter:
    """
    Dedicated Notifications service for assembling and broadcasting HTML 
    price change summaries out of the Pricing Engine workflow.
    """

    @staticmethod
    def send_email_report(report_data):
        if not config.EMAIL_ENABLED or not config.ZOHO_EMAIL or not config.ZOHO_APP_PASSWORD:
            print("\n📧 Email disabled or not configured in variables")
            return False
            
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"Price Update Report - {report_data['date']}"
            msg['From'] = config.ZOHO_EMAIL
            msg['To'] = config.EMAIL_TO
            
            html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
                    .summary {{ background: #f5f5f5; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                    .stat {{ display: inline-block; margin: 10px 20px; }}
                    .stat-value {{ font-size: 24px; font-weight: bold; color: #4CAF50; }}
                    .stat-label {{ font-size: 12px; color: #666; }}
                    .section {{ margin: 20px 0; }}
                    .card {{ background: white; border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }}
                    .price-up {{ color: #e74c3c; }}
                    .price-down {{ color: #27ae60; }}
                    .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>💰 Dumpling Collectibles - Price Update Report</h1>
                    <p>{report_data['date']}</p>
                    {f"<p>Bucket: {report_data['bucket']}</p>" if report_data.get('bucket') else ""}
                </div>
                
                <div class="summary">
                    <div class="stat"><div class="stat-value">{report_data['total_processed']}</div><div class="stat-label">Cards Processed</div></div>
                    <div class="stat"><div class="stat-value">{report_data['total_updated']}</div><div class="stat-label">Cards Updated</div></div>
                    <div class="stat"><div class="stat-value">{report_data['variants_updated']}</div><div class="stat-label">Variants Updated</div></div>
                    <div class="stat"><div class="stat-value">{report_data['shopify_synced']}</div><div class="stat-label">Shopify Synced</div></div>
                </div>
                
                <div class="section">
                    <h2>📊 Summary</h2>
                    <ul>
                        <li>Price increases: {report_data['price_increases']}</li>
                        <li>Price decreases: {report_data['price_decreases']}</li>
                        <li>Failed updates: {report_data['failed']}</li>
                        <li>No change needed: {report_data['no_change']}</li>
                    </ul>
                </div>
                
                <div class="section">
                    <h2>💎 Biggest Price Changes</h2>
            """
            
            if report_data['big_changes']:
                for change in report_data['big_changes'][:10]:
                    direction = "↗️" if change['change'] > 0 else "↘️"
                    color_class = "price-up" if change['change'] > 0 else "price-down"
                    html += f"""
                    <div class="card">
                        <strong>{direction} {change['name']}</strong> (#{change['number']})
                        <br>
                        <span class="{color_class}">
                            ${change['old_price']:.2f} → ${change['new_price']:.2f} 
                            ({change['change']:+.2f} / {change['change_percent']:+.1f}%)
                        </span>
                    </div>
                    """
            else:
                html += "<p>No significant price changes (20%+ and $10+)</p>"
            
            html += f"""
                </div>
                <div class="footer">
                    <p>Automated by Dumpling Collectibles Price Update System</p>
                    <p>Run time: {report_data['run_time']}</p>
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            with smtplib.SMTP(config.ZOHO_SMTP_HOST, config.ZOHO_SMTP_PORT) as server:
                server.starttls()
                server.login(config.ZOHO_EMAIL, config.ZOHO_APP_PASSWORD)
                server.send_message(msg)
            
            print("\n✅ Email report sent successfully!")
            return True
            
        except Exception as e:
            print(f"\n❌ Failed to send email: {str(e)}")
            return False
