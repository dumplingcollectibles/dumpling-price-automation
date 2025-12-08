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
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging
from email_helper import send_buylist_confirmation_email

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow frontend to call API

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database
DATABASE_URL = os.getenv('NEON_DB_URL')

# Shopify (for future features)
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
STORE_NAME = os.getenv('STORE_NAME', 'Dumpling Collectibles')


def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(DATABASE_URL)


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
            email_sent = send_buylist_confirmation_email(
                customer_email=customer['email'],
                customer_name=customer.get('name'),
                buy_offer_id=buy_offer_id,
                quoted_total=total_quote,
                payout_method=payout_method,
                items=valid_items,
                expires_at=expires_at
            )
            
            if email_sent:
                logger.info(f"Confirmation email sent to {customer['email']}")
            else:
                logger.warning(f"Failed to send confirmation email to {customer['email']}")
        except Exception as email_error:
            logger.error(f"Email error: {email_error}")
            # Don't fail the whole request if email fails
        
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
