"""
Buylist API Server - Dumpling Collectibles

Flask API for customer buylist submissions.

Endpoints:
  GET  /api/cards/search?q=charizard    - Search cards for buylist
  POST /api/buylist/submit              - Submit buylist for quote
  GET  /api/health                       - Health check

Usage:
  python buylist_app.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging
import requests

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow frontend to call API

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database
DATABASE_URL = os.getenv('NEON_DB_URL')

# Email Configuration
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
EMAIL_FROM = os.getenv('EMAIL_FROM')
FROM_NAME = os.getenv('FROM_NAME', 'Dumpling Collectibles')
STORE_NAME = os.getenv('STORE_NAME', 'Dumpling Collectibles')
INTERNAL_EMAIL = 'buylist@dumplingcollectibles.com'

# Shopify (for future features)
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')


def get_db_connection():
    """Create database connection"""
    return psycopg.connect(DATABASE_URL)


def send_customer_confirmation_email(customer_email, customer_name, buy_offer_id, quoted_total, payout_method, items, expires_at):
    """Send confirmation email to customer"""
    if not BREVO_API_KEY:
        logger.warning("BREVO_API_KEY not set, skipping customer email")
        return False
    
    # Build items list HTML
    items_html = ""
    for item in items:
        items_html += f"""
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #eee;">{item['card_name']}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee;">{item['set_name']}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{item['condition']}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: center;">{item['quantity']}</td>
            <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right;">${item['price_per_unit']:.2f}</td>
        </tr>
        """
    
    email_data = {
        "sender": {
            "name": FROM_NAME,
            "email": EMAIL_FROM
        },
        "to": [
            {
                "email": customer_email,
                "name": customer_name or "Valued Customer"
            }
        ],
        "subject": f"🎉 Buylist Quote Received - {STORE_NAME}",
        "htmlContent": f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                           color: white; padding: 40px 30px; text-align: center; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                .quote-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; 
                             border-left: 4px solid #667eea; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .total {{ background: #667eea; color: white; padding: 15px; text-align: center; 
                         border-radius: 8px; font-size: 1.3em; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0; font-size: 2em;">✅ Quote Received!</h1>
                    <p style="margin: 10px 0 0 0; opacity: 0.9;">We've received your buylist submission</p>
                </div>
                
                <div class="content">
                    <p>Hi {customer_name or 'there'}!</p>
                    
                    <p>Thanks for submitting your buylist to {STORE_NAME}! We've received your submission and will review it shortly.</p>
                    
                    <div class="quote-box">
                        <h2 style="margin-top: 0; color: #667eea;">Quote Summary</h2>
                        <p><strong>Quote ID:</strong> #{buy_offer_id}</p>
                        <p><strong>Payment Method:</strong> {payout_method.upper()}</p>
                        <p><strong>Total Items:</strong> {len(items)} card{'s' if len(items) > 1 else ''}</p>
                        <p><strong>Quote Expires:</strong> {expires_at.strftime('%B %d, %Y')}</p>
                    </div>
                    
                    <div class="total">
                        <strong>Quoted Total: ${quoted_total:.2f} CAD</strong>
                    </div>
                    
                    <h3>Cards in Your Submission:</h3>
                    <table style="background: white; border-radius: 8px; overflow: hidden;">
                        <thead>
                            <tr style="background: #f0f0f0;">
                                <th style="padding: 10px; text-align: left;">Card</th>
                                <th style="padding: 10px; text-align: left;">Set</th>
                                <th style="padding: 10px; text-align: center;">Condition</th>
                                <th style="padding: 10px; text-align: center;">Qty</th>
                                <th style="padding: 10px; text-align: right;">Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                        </tbody>
                    </table>
                    
                    <div style="background: #e7f3ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #0066cc;">📬 What's Next?</h3>
                        <ol style="margin: 0; padding-left: 20px;">
                            <li>We'll review your submission within 24 hours</li>
                            <li>You'll receive an approval email if everything looks good</li>
                            <li>Ship your cards to us (we'll provide the address)</li>
                            <li>Get paid once we receive and verify your cards!</li>
                        </ol>
                    </div>
                    
                    <p><strong>Important:</strong> This quote expires on {expires_at.strftime('%B %d, %Y')}. Please make sure to respond before then!</p>
                    
                    <p>If you have any questions, feel free to reply to this email.</p>
                    
                    <p>Thanks for choosing {STORE_NAME}!</p>
                    
                    <p style="color: #666; font-size: 0.9em; margin-top: 30px; text-align: center;">
                        <em>This is an automated confirmation email</em>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    }
    
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            },
            json=email_data
        )
        
        if response.status_code == 201:
            logger.info(f"Customer confirmation email sent to {customer_email}")
            return True
        else:
            logger.error(f"Failed to send customer email: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending customer email: {e}")
        return False


def send_internal_notification_email(buy_offer_id, customer_email, customer_name, quoted_total, payout_method, items, expires_at):
    """Send internal notification to buylist team"""
    if not BREVO_API_KEY:
        logger.warning("BREVO_API_KEY not set, skipping internal notification")
        return False
    
    # Build items table HTML
    items_html = ""
    for item in items:
        items_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{item['card_name']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{item['set_name']} #{item['number']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{item['condition']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{item['quantity']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">${item['price_per_unit']:.2f}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right; font-weight: bold;">${item['item_total']:.2f}</td>
        </tr>
        """
    
    email_data = {
        "sender": {
            "name": FROM_NAME,
            "email": EMAIL_FROM
        },
        "to": [
            {
                "email": INTERNAL_EMAIL,
                "name": "Buylist Team"
            }
        ],
        "subject": f"🔔 New Buylist Submission - Quote #{buy_offer_id}",
        "htmlContent": f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                           color: white; padding: 30px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                .info-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; 
                            border-left: 4px solid #667eea; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: white; }}
                th {{ background: #667eea; color: white; padding: 12px; text-align: left; }}
                .total-row {{ background: #f0f0f0; font-weight: bold; font-size: 1.1em; }}
                .action-box {{ background: #fff3cd; border: 2px solid #ffc107; padding: 20px; 
                              border-radius: 8px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">🔔 New Buylist Submission</h1>
                    <p style="margin: 10px 0 0 0; opacity: 0.9;">Action Required</p>
                </div>
                
                <div class="content">
                    <div class="info-box">
                        <h2 style="margin-top: 0; color: #667eea;">Quote Details</h2>
                        <table style="border: none;">
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Quote ID:</strong></td>
                                <td style="padding: 8px 0; border: none;">#{buy_offer_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Customer:</strong></td>
                                <td style="padding: 8px 0; border: none;">{customer_name or 'N/A'} ({customer_email})</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Total Quote:</strong></td>
                                <td style="padding: 8px 0; border: none; font-size: 1.2em; color: #667eea;"><strong>${quoted_total:.2f} CAD</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Payment Method:</strong></td>
                                <td style="padding: 8px 0; border: none;">{payout_method.upper()}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Total Items:</strong></td>
                                <td style="padding: 8px 0; border: none;">{len(items)} card{'s' if len(items) > 1 else ''}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Submitted:</strong></td>
                                <td style="padding: 8px 0; border: none;">{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; border: none;"><strong>Expires:</strong></td>
                                <td style="padding: 8px 0; border: none;">{expires_at.strftime('%B %d, %Y')}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <h3 style="color: #667eea;">📋 Cards Submitted</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Card Name</th>
                                <th>Set</th>
                                <th>Condition</th>
                                <th style="text-align: center;">Qty</th>
                                <th style="text-align: right;">Price/Unit</th>
                                <th style="text-align: right;">Subtotal</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                            <tr class="total-row">
                                <td colspan="5" style="padding: 12px; text-align: right;">TOTAL:</td>
                                <td style="padding: 12px; text-align: right;">${quoted_total:.2f}</td>
                            </tr>
                        </tbody>
                    </table>
                    
                    <div class="action-box">
                        <h3 style="margin-top: 0; color: #856404;">⚠️ Action Required</h3>
                        <p style="margin: 0;">
                            Review this buylist submission and approve/reject items in your admin panel.
                        </p>
                        <p style="margin: 10px 0 0 0;">
                            <strong>Next Steps:</strong>
                        </p>
                        <ol style="margin: 10px 0 0 0;">
                            <li>Review card conditions and quantities in JupyterHub</li>
                            <li>Run Cell 3 (Approve Buylist) to approve or reject items</li>
                            <li>Customer will receive approval email with shipping instructions</li>
                            <li>Wait for cards to arrive at your store</li>
                            <li>Run Cell 4 (Complete Buylist) to process payment</li>
                        </ol>
                    </div>
                    
                    <p style="text-align: center; color: #666; margin-top: 30px;">
                        <em>This is an automated notification from {STORE_NAME}</em>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    }
    
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json"
            },
            json=email_data
        )
        
        if response.status_code == 201:
            logger.info(f"Internal notification sent to {INTERNAL_EMAIL}")
            return True
        else:
            logger.error(f"Failed to send internal notification: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending internal notification: {e}")
        return False


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 500


@app.route('/api/cards/search', methods=['GET'])
def search_cards():
    """
    Search cards available for buylist
    
    Query params:
      q: Search query (card name)
      limit: Max results (default 20)
    
    Returns:
      List of cards with buylist prices for all conditions
    """
    query = request.args.get('q', '').strip()
    limit = int(request.args.get('limit', 20))
    
    if not query:
        return jsonify({'error': 'Query parameter required'}), 400
    
    if len(query) < 2:
        return jsonify({'error': 'Query must be at least 2 characters'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Search cards with buylist prices
        # Only include cards where we're actively buying (buy_cash > 0)
        cursor.execute("""
            SELECT DISTINCT ON (c.id)
                c.id as card_id,
                c.name,
                c.set_name,
                c.set_code,
                c.number,
                c.variant,
                c.img_url,
                c.rarity,
                v.market_price
            FROM cards c
            INNER JOIN products p ON p.card_id = c.id
            INNER JOIN variants v ON v.product_id = p.id
            WHERE 
                c.name ILIKE %s
                AND v.condition = 'NM'
                AND v.buy_cash > 0
            ORDER BY c.id, c.name
            LIMIT %s
        """, (f'%{query}%', limit))
        
        cards = cursor.fetchall()
        
        # For each card, get buylist prices for all conditions
        results = []
        for card in cards:
            card_id = card['card_id']
            
            # Get all condition prices
            cursor.execute("""
                SELECT 
                    v.condition,
                    v.buy_cash,
                    v.buy_credit,
                    v.market_price,
                    v.inventory_qty
                FROM variants v
                INNER JOIN products p ON p.id = v.product_id
                WHERE 
                    p.card_id = %s
                    AND v.buy_cash IS NOT NULL
                    AND v.buy_cash > 0
                ORDER BY 
                    CASE v.condition
                        WHEN 'NM' THEN 1
                        WHEN 'LP' THEN 2
                        WHEN 'MP' THEN 3
                        WHEN 'HP' THEN 4
                        WHEN 'DMG' THEN 5
                    END
            """, (card_id,))
            
            conditions = cursor.fetchall()
            
            if conditions:
                buylist_prices = {}
                for cond in conditions:
                    buylist_prices[cond['condition']] = {
                        'cash': float(cond['buy_cash']) if cond['buy_cash'] else 0,
                        'credit': float(cond['buy_credit']) if cond['buy_credit'] else 0
                    }
                
                results.append({
                    'card_id': card_id,
                    'name': card['name'],
                    'set_name': card['set_name'],
                    'set_code': card['set_code'],
                    'number': card['number'],
                    'variant': card['variant'],
                    'img_url': card['img_url'],
                    'rarity': card['rarity'],
                    'market_price': float(card['market_price']) if card['market_price'] else 0,
                    'buylist_prices': buylist_prices
                })
        
        cursor.close()
        conn.close()
        
        logger.info(f"Search '{query}' returned {len(results)} results")
        
        return jsonify({
            'success': True,
            'query': query,
            'results': results,
            'count': len(results)
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': 'Search failed', 'details': str(e)}), 500


@app.route('/api/buylist/submit', methods=['POST'])
def submit_buylist():
    """
    Submit buylist for quote
    
    Body:
    {
      "customer": {
        "email": "john@example.com",
        "name": "John Doe" (optional)
      },
      "payout_method": "cash" or "credit",
      "cards": [
        {
          "card_id": 123,
          "condition": "NM",
          "quantity": 1
        }
      ]
    }
    
    Returns:
      Quote details and buy_offer_id
    """
    data = request.get_json()
    
    # Validate input
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    customer = data.get('customer', {})
    payout_method = data.get('payout_method', '').lower()
    cards = data.get('cards', [])
    
    # Validation
    if not customer.get('email'):
        return jsonify({'error': 'Customer email required'}), 400
    
    if '@' not in customer['email']:
        return jsonify({'error': 'Invalid email address'}), 400
    
    if payout_method not in ['cash', 'credit']:
        return jsonify({'error': 'Payout method must be "cash" or "credit"'}), 400
    
    if not cards or len(cards) == 0:
        return jsonify({'error': 'At least one card required'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Find or create user
        cursor.execute("SELECT id FROM users WHERE email = %s", (customer['email'],))
        user = cursor.fetchone()
        
        if user:
            user_id = user['id']
        else:
            # Create new user
            cursor.execute("""
                INSERT INTO users (email, name, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                RETURNING id
            """, (customer['email'], customer.get('name')))
            user_id = cursor.fetchone()['id']
            conn.commit()
        
        # Calculate total quote
        total_quote = 0
        valid_items = []
        
        for item in cards:
            card_id = item.get('card_id')
            condition = item.get('condition', '').upper()
            quantity = int(item.get('quantity', 1))
            
            if not card_id or not condition:
                continue
            
            if quantity < 1:
                continue
            
            # Get buylist price for this card and condition
            cursor.execute("""
                SELECT 
                    v.buy_cash,
                    v.buy_credit,
                    c.name,
                    c.set_name,
                    c.number
                FROM variants v
                INNER JOIN products p ON p.id = v.product_id
                INNER JOIN cards c ON c.id = p.card_id
                WHERE 
                    p.card_id = %s
                    AND v.condition = %s
                    AND v.buy_cash > 0
            """, (card_id, condition))
            
            variant = cursor.fetchone()
            
            if not variant:
                logger.warning(f"Card {card_id} condition {condition} not found or not buying")
                continue
            
            # Get price based on payout method
            price_per_unit = float(variant['buy_cash'] if payout_method == 'cash' else variant['buy_credit'])
            item_total = price_per_unit * quantity
            total_quote += item_total
            
            valid_items.append({
                'card_id': card_id,
                'card_name': variant['name'],
                'set_name': variant['set_name'],
                'number': variant['number'],
                'condition': condition,
                'quantity': quantity,
                'price_per_unit': price_per_unit,
                'item_total': item_total
            })
        
        if not valid_items:
            cursor.close()
            conn.close()
            return jsonify({'error': 'No valid cards in submission'}), 400
        
        # Create buy_offer
        expires_at = datetime.now() + timedelta(days=7)  # Quote expires in 7 days
        
        cursor.execute("""
            INSERT INTO buy_offers (
                user_id,
                cash_or_credit,
                quoted_total_cad,
                status,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, 'quoted', %s, NOW(), NOW())
            RETURNING id
        """, (user_id, payout_method, total_quote, expires_at))
        
        buy_offer_id = cursor.fetchone()['id']
        
        # Insert buy_offer_items
        for item in valid_items:
            cursor.execute("""
                INSERT INTO buy_offer_items (
                    buy_offer_id,
                    card_id,
                    condition,
                    quantity,
                    quoted_price_per_unit
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                buy_offer_id,
                item['card_id'],
                item['condition'],
                item['quantity'],
                item['price_per_unit']
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Buylist submitted: ID={buy_offer_id}, User={customer['email']}, Total=${total_quote:.2f}")
        
        # Send confirmation email to customer
        try:
            customer_email_sent = send_customer_confirmation_email(
                customer_email=customer['email'],
                customer_name=customer.get('name'),
                buy_offer_id=buy_offer_id,
                quoted_total=total_quote,
                payout_method=payout_method,
                items=valid_items,
                expires_at=expires_at
            )
            
            if customer_email_sent:
                logger.info(f"Customer confirmation email sent to {customer['email']}")
            else:
                logger.warning(f"Failed to send customer confirmation email")
                
        except Exception as email_error:
            logger.error(f"Customer email error: {email_error}")
        
        # Send internal notification to buylist team
        try:
            internal_email_sent = send_internal_notification_email(
                buy_offer_id=buy_offer_id,
                customer_email=customer['email'],
                customer_name=customer.get('name'),
                quoted_total=total_quote,
                payout_method=payout_method,
                items=valid_items,
                expires_at=expires_at
            )
            
            if internal_email_sent:
                logger.info(f"Internal notification sent to {INTERNAL_EMAIL}")
            else:
                logger.warning(f"Failed to send internal notification")
                
        except Exception as email_error:
            logger.error(f"Internal notification error: {email_error}")
        
        return jsonify({
            'success': True,
            'buy_offer_id': buy_offer_id,
            'quoted_total': round(total_quote, 2),
            'payout_method': payout_method,
            'item_count': len(valid_items),
            'items': valid_items,
            'expires_at': expires_at.isoformat(),
            'message': f'Quote submitted! Total: ${total_quote:.2f} {payout_method}'
        }), 201
        
    except Exception as e:
        logger.error(f"Submit error: {e}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Submission failed', 'details': str(e)}), 500


@app.route('/', methods=['GET'])
def index():
    """Root endpoint"""
    return jsonify({
        'service': 'Dumpling Collectibles Buylist API',
        'status': 'running',
        'endpoints': {
            'health': 'GET /api/health',
            'search': 'GET /api/cards/search?q=charizard',
            'submit': 'POST /api/buylist/submit'
        }
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
