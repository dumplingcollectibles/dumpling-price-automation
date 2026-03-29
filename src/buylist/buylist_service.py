import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from src.config import config
from src.buylist.buylist_config import buylist_config
from src.notifications.buylist_reporter import BuylistReporter

class BuylistService:
    """
    Business Logic Tier for Dumpling Collectibles Buylist.
    Manages card searching, quote calculations, user synchronization, 
    and transaction persistence for the customer-facing buylist storefront.
    """

    def __init__(self, db_conn=None):
        self.conn = db_conn or psycopg2.connect(config.DATABASE_URL)
        self.reporter = BuylistReporter()

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def search_cards(self, query, limit=None):
        """Finds cards where the store is actively offering a buylist price."""
        if not limit:
            limit = buylist_config.SEARCH_LIMIT_DEFAULT
            
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Step 1: Find matching distinct cards
            cursor.execute("""
                SELECT DISTINCT ON (c.id)
                    c.id as card_id, c.name, c.set_name, c.set_code, c.number,
                    c.variant, c.img_url, c.rarity, v.market_price
                FROM cards c
                INNER JOIN products p ON p.card_id = c.id
                INNER JOIN variants v ON v.product_id = p.id
                WHERE c.name ILIKE %s AND v.condition = 'NM' AND v.buy_cash > 0
                ORDER BY c.id, c.name LIMIT %s
            """, (f'%{query}%', limit))
            
            cards = cursor.fetchall()
            results = []
            
            # Step 2: Inject all available condition quotes per card
            for card in cards:
                cursor.execute("""
                    SELECT v.condition, v.buy_cash, v.buy_credit, v.market_price, v.inventory_qty
                    FROM variants v
                    INNER JOIN products p ON p.id = v.product_id
                    WHERE p.card_id = %s AND v.buy_cash IS NOT NULL AND v.buy_cash > 0
                    ORDER BY CASE v.condition
                        WHEN 'NM' THEN 1 WHEN 'LP' THEN 2 WHEN 'MP' THEN 3 WHEN 'HP' THEN 4
                        WHEN 'DMG' THEN 5 END
                """, (card['card_id'],))
                
                conditions = cursor.fetchall()
                if conditions:
                    buylist_prices = {
                        c['condition']: {
                            'cash': float(c['buy_cash']),
                            'credit': float(c['buy_credit'])
                        } for c in conditions
                    }
                    
                    results.append({
                        **card,
                        'market_price': float(card['market_price']) if card['market_price'] else 0,
                        'buylist_prices': buylist_prices
                    })
            return results
        finally:
            cursor.close()

    def submit_quote(self, customer_data, payout_method, cards):
        """Processes a full buylist submission, calculating totals and notifying both parties."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            # 1. Resolve User
            cursor.execute("SELECT id FROM users WHERE email = %s", (customer_data['email'],))
            user = cursor.fetchone()
            if not user:
                cursor.execute("INSERT INTO users (email, name, created_at, updated_at) VALUES (%s, %s, NOW(), NOW()) RETURNING id", (customer_data['email'], customer_data.get('name')))
                user_id = cursor.fetchone()['id']
            else:
                user_id = user['id']

            # 2. Calculate Totals via Database price verification
            total_quote = 0
            valid_items = []
            for item in cards:
                cursor.execute("""
                    SELECT v.buy_cash, v.buy_credit, c.name, c.set_name, c.number
                    FROM variants v
                    INNER JOIN products p ON p.id = v.product_id
                    INNER JOIN cards c ON c.id = p.card_id
                    WHERE p.card_id = %s AND v.condition = %s AND v.buy_cash > 0
                """, (item['card_id'], item['condition'].upper()))
                
                variant = cursor.fetchone()
                if not variant: continue
                
                price_per_unit = float(variant['buy_cash'] if payout_method == 'cash' else variant['buy_credit'])
                total_quote += (price_per_unit * item['quantity'])
                valid_items.append({
                    **item,
                    'card_name': variant['name'], 'set_name': variant['set_name'], 'number': variant['number'],
                    'price_per_unit': price_per_unit, 'item_total': price_per_unit * item['quantity']
                })

            if not valid_items: return None

            # 3. Persist Offer
            expires_at = datetime.now() + timedelta(days=buylist_config.QUOTE_EXPIRY_DAYS)
            cursor.execute("""
                INSERT INTO buy_offers (user_id, cash_or_credit, quoted_total_cad, status, expires_at, created_at, updated_at)
                VALUES (%s, %s, %s, 'quoted', %s, NOW(), NOW()) RETURNING id
            """, (user_id, payout_method, total_quote, expires_at))
            buy_offer_id = cursor.fetchone()['id']

            for item in valid_items:
                cursor.execute("""
                    INSERT INTO buy_offer_items (buy_offer_id, card_id, condition, quantity, quoted_price_per_unit)
                    VALUES (%s, %s, %s, %s, %s)
                """, (buy_offer_id, item['card_id'], item['condition'], item['quantity'], item['price_per_unit']))

            self.conn.commit()

            # 4. Trigger Notifications
            report_data = {
                'quote_id': buy_offer_id, 'customer_email': customer_data['email'], 'customer_name': customer_data.get('name'),
                'total': total_quote, 'payout_method': payout_method, 'items': valid_items, 'expires_at': expires_at
            }
            self.reporter.send_customer_confirmation(report_data)
            self.reporter.send_internal_notification(report_data)

            return { 'success': True, 'buy_offer_id': buy_offer_id, 'total': total_quote, 'expires_at': expires_at, 'items': valid_items }
            
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()
