import hmac
import hashlib
import base64
import json
import requests
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from src.config import config
from src.store_credit.store_credit_service import StoreCreditService

logger = logging.getLogger(__name__)

class WebhookService:
    """
    Business Logic Service for processing incoming Shopify webhooks.
    Handles HMAC verification, user synchronization, inventory ledger 
    updates, and store credit usage recording.
    """

    def __init__(self, db_conn=None):
        self.conn = db_conn or psycopg2.connect(config.DATABASE_URL)
        self.store_credit = StoreCreditService(db_conn=self.conn)

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    @staticmethod
    def verify_shopify_hmac(data, hmac_header):
        """Verifies the integrity of the webhook using the secret key."""
        if not config.SHOPIFY_WEBHOOK_SECRET:
            logger.warning("SHOPIFY_WEBHOOK_SECRET not set, skipping verification")
            return True
        if not hmac_header:
            return False
            
        digest = hmac.new(
            config.SHOPIFY_WEBHOOK_SECRET.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
        
        provided_signature = base64.b64decode(hmac_header)
        return hmac.compare_digest(digest, provided_signature)

    def get_or_create_user(self, email, customer_data):
        """Syncs the Shopify customer to the internal Dumpling user table."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if user:
            user_id = user['id']
        else:
            name = (customer_data.get('first_name', '') + ' ' + customer_data.get('last_name', '')).strip() or None
            addr = customer_data.get('default_address', {})
            address_json = json.dumps({
                'street': addr.get('address1', ''), 'city': addr.get('city', ''),
                'province': addr.get('province', ''), 'postal': addr.get('zip', ''),
                'country': addr.get('country', '')
            }) if addr else None
            
            cursor.execute("""
                INSERT INTO users (email, name, shopify_customer_id, address)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (email, name, str(customer_data.get('id', '')), address_json))
            user_id = cursor.fetchone()['id']
            self.conn.commit()
            
        cursor.close()
        return user_id

    def fetch_full_shopify_order(self, order_id):
        """Deeper dive into Shopify's REST API to recover transaction logs missing from webhooks."""
        url = f"https://{config.SHOPIFY_SHOP_URL}/admin/api/{config.SHOPIFY_API_VERSION}/orders/{order_id}.json"
        try:
            response = requests.get(
                url, headers={'X-Shopify-Access-Token': config.SHOPIFY_ACCESS_TOKEN}, timeout=10
            )
            if response.status_code == 200:
                return response.json()['order']
        except Exception:
            return None
        return None

    def process_order_webhook(self, order_data):
        """Processes the full order lifecycle from Shopify into our internal Postgres state."""
        logger.info(f"Processing order: {order_data.get('order_number')}")
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # 1. Resolve User
            customer = order_data.get('customer', {})
            email = customer.get('email') or f"guest_{order_data['id']}@placeholder.com"
            user_id = self.get_or_create_user(email, customer)

            # 2. Extract & Resolve Payment Gateways
            gateways = [str(g).lower() for g in order_data.get('payment_gateway_names', [])]
            gift_card_total = 0.0
            gift_card_codes = []
            
            if 'gift_card' in gateways:
                full_order = self.fetch_full_shopify_order(order_data['id'])
                if full_order:
                    for txn in full_order.get('transactions', []):
                        if txn.get('gateway') == 'gift_card' and txn.get('status') == 'success':
                            amount = abs(float(txn.get('amount', 0)))
                            auth = txn.get('authorization') or txn.get('receipt', {}).get('gift_card_last_characters')
                            gift_card_total += amount
                            if auth and str(auth) not in gift_card_codes:
                                gift_card_codes.append(str(auth))

            # 3. Create Order Entry
            total_price = float(order_data.get('total_price', 0))
            cursor.execute("""
                INSERT INTO orders (
                    shopify_order_id, user_id, order_date, order_total,
                    order_amount_cash, order_amount_credit, net_order_amount,
                    tax, shipping, payment_method, gift_card_codes, 
                    gift_card_amount_used, status
                ) VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                str(order_data['id']), user_id, total_price,
                total_price - gift_card_total, gift_card_total, float(order_data.get('subtotal_price', 0)),
                float(order_data.get('total_tax', 0)), 
                float(order_data.get('total_shipping_price_set', {}).get('shop_money', {}).get('amount', 0)),
                'gift_card' if 'gift_card' in gateways else 'credit_card',
                gift_card_codes if gift_card_codes else None,
                gift_card_total if gift_card_total > 0 else None, 'paid'
            ))
            order_id = cursor.fetchone()['id']

            # 4. Sync Inventory Line Items
            for item in order_data.get('line_items', []):
                variant_id = str(item.get('variant_id'))
                qty = int(item.get('quantity', 1))
                
                cursor.execute("SELECT id, inventory_qty, cost_basis_avg FROM variants WHERE shopify_variant_id = %s", (variant_id,))
                variant = cursor.fetchone()
                if not variant: continue
                
                # Update variant qty
                cursor.execute("UPDATE variants SET inventory_qty = %s WHERE id = %s", (variant['inventory_qty'] - qty, variant['id']))
                # Log transaction
                cursor.execute("""
                    INSERT INTO inventory_transactions (variant_id, transaction_type, quantity, unit_cost, reference_type, reference_id, created_at)
                    VALUES (%s, 'sale', %s, %s, 'order', %s, NOW())
                """, (variant['id'], -qty, float(variant['cost_basis_avg'] or 0), order_id))

            # 5. Ledger Sync (If gift card was used)
            if gift_card_total > 0:
                self.store_credit.record_transaction(
                    user_id=user_id,
                    amount=-gift_card_total,
                    transaction_type='order_payment',
                    reference_type='order',
                    reference_id=order_id,
                    gift_card_code=gift_card_codes[0] if gift_card_codes else None,
                    notes=f"Store credit used on order #{order_data.get('order_number')}"
                )

            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()
