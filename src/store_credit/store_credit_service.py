import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from src.config import config
from src.store_credit.store_credit_config import store_credit_config

from src.notifications.store_credit_reporter import StoreCreditReporter

class StoreCreditService:
    """
    Business Logic Service for handling Dumpling Collectibles store credit.
    
    This abstracts all Postgres DB connections, Shopify Gift Card formations, 
    and transaction ledgers out of the CLI/API controllers.
    """
    
    def __init__(self, db_conn=None):
        # Supports dependency injection for testing, or creates its own connection
        self.conn = db_conn or psycopg2.connect(config.DATABASE_URL)
        self.reporter = StoreCreditReporter()
        
    def __del__(self):
        # Automatically tear down the database connection when the service is destroyed
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def find_user(self, email, create_if_missing=False):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, email, name FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if user:
            cursor.close()
            return user
            
        if create_if_missing:
            cursor.execute(
                "INSERT INTO users (email, created_at, updated_at) VALUES (%s, NOW(), NOW()) RETURNING id", 
                (email,)
            )
            user_id = cursor.fetchone()['id']
            self.conn.commit()
            cursor.close()
            return {'id': user_id, 'email': email, 'name': None}
            
        cursor.close()
        return None

    def get_balance(self, user_id):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT balance_after FROM store_credit_ledger WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id,)
        )
        result = cursor.fetchone()
        cursor.close()
        return float(result['balance_after']) if result else 0.0

    def get_history(self, user_id):
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, amount, transaction_type, reference_type, reference_id, 
                   balance_after, shopify_gift_card_code, notes, created_at
            FROM store_credit_ledger
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
        """, (user_id,))
        transactions = cursor.fetchall()
        cursor.close()
        return transactions

    def create_shopify_gift_card(self, amount, note):
        shop_url = config.SHOPIFY_SHOP_URL
        if shop_url and not shop_url.startswith('https://'):
            shop_url = f"https://{shop_url}"
            
        url = f"{shop_url}/admin/api/{config.SHOPIFY_API_VERSION}/gift_cards.json"
        headers = {
            "X-Shopify-Access-Token": config.SHOPIFY_ACCESS_TOKEN,
            "Content-Type": "application/json"
        }
        
        payload = {
            "gift_card": {
                "initial_value": float(amount),
                "code": None,
                "note": note
            }
        }
        
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 201:
            return response.json()['gift_card']['code']
        return None

    def record_transaction(self, user_id, amount, transaction_type, reference_type=None, reference_id=None, gift_card_code=None, notes=None):
        current_balance = self.get_balance(user_id)
        new_balance = current_balance + float(amount)
        
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO store_credit_ledger 
            (user_id, amount, transaction_type, reference_type, reference_id, balance_after, shopify_gift_card_code, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, amount, transaction_type, reference_type, reference_id, new_balance, gift_card_code, notes))
        
        self.conn.commit()
        cursor.close()
        return current_balance, new_balance

    def issue_credit(self, email, amount, transaction_type=store_credit_config.DEFAULT_TRANSACTION_TYPE, reason=None, create_gift_card=False, reference_type=None, reference_id=None, notify=False):
        """High-level controller wrapper executing the full issue-credit workflow dynamically."""
        user = self.find_user(email, create_if_missing=True)
        user_id = user['id']
        
        gift_card_code = None
        if create_gift_card and amount > 0:
            note = store_credit_config.DEFAULT_GIFT_CARD_NOTE_TEMPLATE.format(email=email)
            gift_card_code = self.create_shopify_gift_card(amount, note=note)
            
        old_balance, new_balance = self.record_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type,
            reference_type=reference_type,
            reference_id=reference_id,
            gift_card_code=gift_card_code,
            notes=reason
        )
        
        email_sent = False
        if notify and amount > 0:
            email_sent = self.reporter.send_gift_card_notification(
                customer_email=email,
                gift_card_code=gift_card_code, 
                amount=amount,
                reason=reason,
                balance_after=new_balance
            )
            
        return {
            "user_id": user_id,
            "old_balance": old_balance,
            "new_balance": new_balance,
            "gift_card_code": gift_card_code,
            "email_sent": email_sent
        }
