"""
Buylist API Controller - Dumpling Collectibles
Flask API for customer buylist submissions.
Refactored into 3-Tier Layer architecture.

Usage:
  python -m src.buylist.buylist_app
"""
import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

from src.config import config
from src.buylist.buylist_service import BuylistService
from src.buylist.buylist_config import buylist_config

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize domain service
service = BuylistService()

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint confirming database heartbeat."""
    try:
        # Simple search for a dummy card to verify DB connection
        service.search_cards('Charizard', limit=1)
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/api/cards/search', methods=['GET'])
def search_cards():
    """
    Search cards available for buylist.
    Query params:
      q: Search query (card name)
      limit: Max results
    """
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', buylist_config.SEARCH_LIMIT_DEFAULT)
    
    if len(query) < buylist_config.MIN_SEARCH_QUERY_LENGTH:
        return jsonify({'error': f'Query must be at least {buylist_config.MIN_SEARCH_QUERY_LENGTH} characters'}), 400
    
    try:
        results = service.search_cards(query, limit=int(limit))
        return jsonify({
            'success': True,
            'query': query,
            'results': results,
            'count': len(results)
        })
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': 'Search failed'}), 500

@app.route('/api/buylist/submit', methods=['POST'])
def submit_buylist():
    """
    Submit buylist for quote processing.
    Delegates all validation and persistence to the domain Service.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    customer = data.get('customer', {})
    payout_method = data.get('payout_method', '').lower()
    cards = data.get('cards', [])
    
    if not customer.get('email') or '@' not in customer['email']:
        return jsonify({'error': 'Valid customer email required'}), 400
    
    if payout_method not in buylist_config.PAYOUT_METHODS:
        return jsonify({'error': f"Payout method must be one of {buylist_config.PAYOUT_METHODS}"}), 400
    
    if not cards:
        return jsonify({'error': 'At least one card required'}), 400
    
    try:
        result = service.submit_quote(customer, payout_method, cards)
        if not result:
            return jsonify({'error': 'No valid items found in submission'}), 400
            
        return jsonify({
            'success': True,
            'buy_offer_id': result['buy_offer_id'],
            'quoted_total': round(result['total'], 2),
            'payout_method': payout_method,
            'item_count': len(result['items']),
            'expires_at': result['expires_at'].isoformat(),
            'message': f"Quote submitted! ID: #{result['buy_offer_id']}"
        }), 201
    except Exception as e:
        logger.error(f"Submission error: {e}")
        return jsonify({'error': 'Submission failed'}), 500

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'service': f"{config.STORE_NAME} Buylist API",
        'status': 'running',
        'endpoints': {
            'health': 'GET /api/health',
            'search': 'GET /api/cards/search?q=charizard',
            'submit': 'POST /api/buylist/submit'
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('BUYLIST_API_PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
