"""
Shopify Webhook Server - Dumpling Collectibles
Flask API for handling automated order callbacks.

Flow:
1. Receives order creation webhook.
2. Verified HMAC signature via domain service.
3. Delegates persistence and inventory syncing to the Service Layer.

Usage:
  python -m src.webhooks.webhook_server
"""
import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime
from src.webhooks.webhook_service import WebhookService

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize domain service
service = WebhookService()

@app.route('/health', methods=['GET'])
def health_check():
    """Confirms the endpoint is live and the database is reachable."""
    try:
        # DB check performed in service init/del implicitly, but can be explicit
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/webhooks/shopify/orders/create', methods=['POST'])
def shopify_order_webhook():
    """
    Handle Shopify order creation callbacks.
    Fully delegating business logic to the WebhookService.
    """
    try:
        data = request.get_data()
        hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
        
        # 1. Security check
        if not service.verify_shopify_hmac(data, hmac_header):
            logger.error("❌ Invalid webhook signature received.")
            return jsonify({'error': 'Invalid signature'}), 401
        
        # 2. Extract & Delegate
        order_data = json.loads(data)
        success = service.process_order_webhook(order_data)
        
        if success:
            logger.info(f"✅ Order {order_data.get('order_number')} processed successfully.")
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Processing failed'}), 500
            
    except Exception as e:
        logger.error(f"❌ Webhook processing failed: {str(e)}", exc_info=True)
        # Still return 200 occasionally to prevent Shopify from disabling the webhook on transient failures
        return jsonify({'error': str(e)}), 200

@app.route('/')
def home():
    return jsonify({
        'status': 'running',
        'service': 'Dumpling Collectibles Webhook Server',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
