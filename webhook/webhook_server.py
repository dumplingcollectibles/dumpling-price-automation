"""
Shopify Webhook Server - Order Processing

Receives Shopify order webhooks and updates database automatically.

Flow:
1. Shopify sends order webhook (POST request)
2. Verify signature (security check)
3. Parse order data
4. Update database (inventory, orders, transactions)
5. Respond 200 OK to Shopify
"""

from flask import Flask, request, jsonify
import hmac
import hashlib
import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import logging

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')
SHOPIFY_WEBHOOK_SECRET = os.environ.get('SHOPIFY_WEBHOOK_SECRET')

# Verify required environment variables
if not DATABASE_URL:
    logger.error("DATABASE_URL not set!")
if not SHOPIFY_WEBHOOK_SECRET:
    logger.error("SHOPIFY_WEBHOOK_SECRET not set!")


def verify_webhook(data, hmac_header):
    """
    Verify that webhook actually came from Shopify
    
    Args:
        data: Raw request body (bytes)
        hmac_header: X-Shopify-Hmac-Sha256 header value
    
    Returns:
        bool: True if signature is valid
    """
    if not SHOPIFY_WEBHOOK_SECRET:
        logger.warning("No webhook secret configured - skipping verification!")
        return True
    
    # Calculate expected signature
    expected_signature = hmac.new(
        SHOPIFY_WEBHOOK_SECRET.encode('utf-8'),
        data,
        hashlib.sha256
    ).digest()
    
    # Compare with provided signature
    import base64
    provided_signature = base64.b64decode(hmac_header)
    
    return hmac.compare_digest(expected_signature, provided_signature)


def get_or_create_user(email, customer_data):
    """
    Get existing user or create new one
    
    Args:
        email: Customer email
        customer_data: Customer data from Shopify
    
    Returns:
        int: user_id
    """
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check if user exists
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    
    if user:
        user_id = user['id']
    else:
        # Create new user
        name = customer_data.get('first_name', '') + ' ' + customer_data.get('last_name', '')
        name = name.strip() or None
        
        shopify_customer_id = str(customer_data.get('id', ''))
        
        # Get address
        default_address = customer_data.get('default_address', {})
        address = None
        if default_address:
            address = {
                'street': default_address.get('address1', ''),
                'city': default_address.get('city', ''),
                'province': default_address.get('province', ''),
                'postal': default_address.get('zip', ''),
                'country': default_address.get('country', '')
            }
        
        cursor.execute("""
            INSERT INTO users (email, name, shopify_customer_id, address)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (email, name, shopify_customer_id, json.dumps(address) if address else None))
        
        user_id = cursor.fetchone()['id']
        logger.info(f"Created new user: {email} (id={user_id})")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return user_id


def process_order(order_data):
    """
    Process Shopify order and update database
    
    Args:
        order_data: Order data from Shopify webhook
    """
    logger.info(f"Processing order: {order_data.get('order_number')}")
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Extract order info
        shopify_order_id = str(order_data['id'])
        order_number = order_data.get('order_number')
        
        # Get or create user
        customer = order_data.get('customer', {})
        customer_email = customer.get('email')
        
        if not customer_email:
            logger.warning(f"Order {order_number} has no customer email - using placeholder")
            customer_email = f"guest_{shopify_order_id}@placeholder.com"
        
        user_id = get_or_create_user(customer_email, customer)
        
        # Order totals
        total_price = float(order_data.get('total_price', 0))
        subtotal = float(order_data.get('subtotal_price', 0))
        total_tax = float(order_data.get('total_tax', 0))
        shipping = float(order_data.get('total_shipping_price_set', {}).get('shop_money', {}).get('amount', 0))
        
        # Payment method detection
        payment_gateway_names = order_data.get('payment_gateway_names', [])
        if 'gift_card' in [g.lower() for g in payment_gateway_names]:
            payment_method = 'gift_card'
        elif any(keyword in str(payment_gateway_names).lower() for keyword in ['credit', 'card', 'visa', 'mastercard']):
            payment_method = 'credit_card'
        else:
            payment_method = 'other'
        
        # Gift card info - properly extract from Shopify order data
        gift_cards = []
        gift_card_total = 0.0
        
        # Method 1: Check for gift_card in payment_gateway_names
        has_gift_card = 'gift_card' in [str(g).lower() for g in payment_gateway_names]
        
        # Method 2: Check transactions for gift card payments
        transactions = order_data.get('transactions', [])
        for transaction in transactions:
            gateway = str(transaction.get('gateway', '')).lower()
            kind = str(transaction.get('kind', '')).lower()
            status = str(transaction.get('status', '')).lower()
            
            # Gift card transactions have gateway='gift_card' or kind='gift_card'
            if 'gift_card' in gateway or kind == 'sale':
                if gateway == 'gift_card' or transaction.get('payment_details', {}).get('gift_card_id'):
                    amount = abs(float(transaction.get('amount', 0)))
                    if amount > 0 and status == 'success':
                        auth_code = transaction.get('authorization') or transaction.get('receipt', {}).get('gift_card_id')
                        if auth_code:
                            gift_cards.append(str(auth_code))
                        gift_card_total += amount
        
        # Method 3: Check current_total_discounts_set for gift card discounts
        # Sometimes Shopify lists gift cards as discounts
        if gift_card_total == 0:
            # Check order-level gift card data
            order_gift_cards = order_data.get('gift_cards', [])
            for gc in order_gift_cards:
                amount = abs(float(gc.get('amount', 0)))
                code = gc.get('code') or gc.get('last_characters')
                if amount > 0:
                    gift_card_total += amount
                    if code:
                        gift_cards.append(str(code))
        
        # Method 4: Check financial_status and total_discounts
        # If still no gift card found but payment_gateway_names includes it
        if gift_card_total == 0 and has_gift_card:
            # Calculate from price differences
            current_total = float(order_data.get('current_total_price', total_price))
            if current_total < total_price:
                potential_gift_card = total_price - current_total
                if potential_gift_card > 0:
                    gift_card_total = potential_gift_card
                    logger.info(f"Inferred gift card amount from price difference: ${gift_card_total:.2f}")
        
        # Calculate cash vs credit amounts
        order_amount_credit = gift_card_total
        order_amount_cash = total_price - gift_card_total
        
        logger.info(f"Payment breakdown: Total=${total_price:.2f}, Cash=${order_amount_cash:.2f}, Credit=${order_amount_credit:.2f}")
        if gift_cards:
            logger.info(f"Gift cards used: {gift_cards}")
        
        # Create order record
        cursor.execute("""
            INSERT INTO orders (
                shopify_order_id, user_id, order_date, order_total,
                order_amount_cash, order_amount_credit,
                net_order_amount, tax, shipping, payment_method,
                gift_card_codes, gift_card_amount_used, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            shopify_order_id,
            user_id,
            datetime.now(),
            total_price,
            order_amount_cash,
            order_amount_credit,
            subtotal,
            total_tax,
            shipping,
            payment_method,
            gift_cards if gift_cards else None,
            gift_card_total if gift_card_total > 0 else None,
            'paid'
        ))
        
        order_id = cursor.fetchone()['id']
        logger.info(f"Created order record (id={order_id})")
        
        # Process line items
        line_items = order_data.get('line_items', [])
        
        for item in line_items:
            shopify_variant_id = str(item.get('variant_id'))
            quantity = int(item.get('quantity', 1))
            unit_price = float(item.get('price', 0))
            subtotal_item = unit_price * quantity
            
            # Find variant in database
            cursor.execute("""
                SELECT id, inventory_qty, cost_basis_avg
                FROM variants
                WHERE shopify_variant_id = %s
            """, (shopify_variant_id,))
            
            variant = cursor.fetchone()
            
            if not variant:
                logger.warning(f"Variant {shopify_variant_id} not found in database - skipping")
                continue
            
            variant_id = variant['id']
            current_qty = variant['inventory_qty']
            cost_basis = float(variant['cost_basis_avg'] or 0)
            
            # Create order item
            cursor.execute("""
                INSERT INTO order_items (order_id, variant_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (order_id, variant_id, quantity, unit_price, subtotal_item))
            
            logger.info(f"Created order item: variant_id={variant_id}, qty={quantity}")
            
            # Update inventory
            new_qty = current_qty - quantity
            cursor.execute("""
                UPDATE variants
                SET inventory_qty = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_qty, variant_id))
            
            logger.info(f"Updated inventory: variant_id={variant_id}, {current_qty} → {new_qty}")
            
            # Log inventory transaction
            cursor.execute("""
                INSERT INTO inventory_transactions (
                    variant_id, transaction_type, quantity, unit_cost,
                    reference_type, reference_id, notes, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                variant_id,
                'sale',
                -quantity,  # Negative for sale
                cost_basis,
                'order',
                order_id,
                f"Shopify order #{order_number}"
            ))
            
            # Calculate profit
            profit = (unit_price - cost_basis) * quantity
            logger.info(f"Profit on sale: ${profit:.2f} (sold ${unit_price}, cost ${cost_basis}, qty {quantity})")
        
        # Update store credit ledger if gift card was used
        if gift_card_total > 0 and gift_cards:
            # Get current balance
            cursor.execute("""
                SELECT balance_after 
                FROM store_credit_ledger 
                WHERE user_id = %s 
                ORDER BY created_at DESC, id DESC 
                LIMIT 1
            """, (user_id,))
            
            balance_result = cursor.fetchone()
            current_balance = float(balance_result['balance_after']) if balance_result else 0.0
            new_balance = current_balance - gift_card_total
            
            # Record gift card usage in ledger
            cursor.execute("""
                INSERT INTO store_credit_ledger (
                    user_id,
                    amount,
                    transaction_type,
                    reference_type,
                    reference_id,
                    balance_after,
                    shopify_gift_card_code,
                    notes,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                user_id,
                -gift_card_total,  # Negative for usage
                'order_payment',
                'order',
                order_id,
                new_balance,
                gift_cards[0] if gift_cards else None,  # First gift card code
                f"Store credit used on order #{order_number}"
            ))
            
            logger.info(f"Updated store credit ledger: ${current_balance:.2f} → ${new_balance:.2f}")
        
        # Commit all changes
        conn.commit()
        logger.info(f"✅ Successfully processed order {order_number}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error processing order: {str(e)}", exc_info=True)
        raise
    
    finally:
        cursor.close()
        conn.close()


@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'service': 'Dumpling Collectibles Webhook Server',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/health')
def health():
    """Health check for monitoring"""
    try:
        # Test database connection
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    return jsonify({
        'status': 'healthy',
        'database': db_status,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/webhooks/shopify/orders/create', methods=['POST'])
def shopify_order_webhook():
    """
    Handle Shopify order creation webhook
    
    When customer places order on Shopify, this endpoint:
    1. Verifies webhook signature
    2. Processes order data
    3. Updates database
    4. Returns 200 OK
    """
    try:
        # Get raw request data
        data = request.get_data()
        hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
        
        # Log webhook received
        logger.info("=" * 70)
        logger.info("📦 WEBHOOK RECEIVED")
        logger.info(f"Shopify Shop: {request.headers.get('X-Shopify-Shop-Domain')}")
        logger.info(f"Topic: {request.headers.get('X-Shopify-Topic')}")
        logger.info("=" * 70)
        
        # Verify webhook signature
        if not verify_webhook(data, hmac_header):
            logger.error("❌ Invalid webhook signature!")
            return jsonify({'error': 'Invalid signature'}), 401
        
        logger.info("✅ Webhook signature verified")
        
        # Parse order data
        order_data = json.loads(data)
        
        # Process order
        process_order(order_data)
        
        # Respond success
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"❌ Webhook processing failed: {str(e)}", exc_info=True)
        # Still return 200 to prevent Shopify retries
        return jsonify({'error': str(e)}), 200


if __name__ == '__main__':
    # For local testing
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
