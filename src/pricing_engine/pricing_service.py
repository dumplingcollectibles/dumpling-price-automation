import math
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from src.config import config

class PricingService:
    """
    Business Logic Tier for Dumpling Collectibles Pricing Engine.
    Handles algorithmic logic (10% margins, buylist cash matrices),
    threshold calculations, and isolated raw API/Database access.
    """
    
    # Internal pricing domain thresholds
    MIN_CHANGE_DOLLARS = 0.50
    MIN_CHANGE_PERCENT = 5.0
    BIG_CHANGE_DOLLARS = 10.0
    BIG_CHANGE_PERCENT = 20.0

    @staticmethod
    def get_db_connection():
        """Returns a completely fresh DB connection string. Extremely important for safe parallel execution."""
        return psycopg2.connect(config.DATABASE_URL)

    @staticmethod
    def round_up_to_nearest_50_cents(amount):
        return math.ceil(amount * 2) / 2

    @staticmethod
    def extract_market_price(api_card):
        tcgplayer = api_card.get('tcgplayer', {})
        prices = tcgplayer.get('prices', {})
        for price_type in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil']:
            if price_type in prices:
                price_data = prices[price_type]
                market = price_data.get('market') or price_data.get('mid') or price_data.get('low')
                if market and market > 0:
                    return float(market)
        return None

    @staticmethod
    def calculate_buylist_prices(market_price, condition, nm_buy_cash=None, nm_buy_credit=None):
        """Core math algorithm determining C2B trade payouts"""
        if condition in ['HP', 'DMG']:
            return None, None
        
        if condition == 'NM':
            if market_price < 50:
                cash_pct, credit_pct = 0.60, 0.70
            elif market_price < 100:
                cash_pct, credit_pct = 0.70, 0.80
            else:
                cash_pct, credit_pct = 0.75, 0.85
            return int((market_price * cash_pct) * 2) / 2, int((market_price * credit_pct) * 2) / 2
        elif condition == 'LP':
            return round(nm_buy_cash * 0.75, 2), round(nm_buy_credit * 0.75, 2)
        elif condition == 'MP':
            return round(nm_buy_cash * 0.50, 2), round(nm_buy_credit * 0.50, 2)
        return None, None

    @classmethod
    def should_update_price(cls, old_price, new_price):
        if old_price == 0 or old_price is None:
            return True
        dollar_change = abs(new_price - old_price)
        percent_change = (dollar_change / old_price) * 100
        return dollar_change >= cls.MIN_CHANGE_DOLLARS and percent_change >= cls.MIN_CHANGE_PERCENT

    @classmethod
    def is_big_change(cls, old_price, new_price):
        if old_price == 0 or old_price is None:
            return False
        dollar_change = abs(new_price - old_price)
        percent_change = (dollar_change / old_price) * 100
        return dollar_change >= cls.BIG_CHANGE_DOLLARS and percent_change >= cls.BIG_CHANGE_PERCENT

    def fetch_api_price(self, external_id, retries=5):
        url = f"{config.POKEMONTCG_API_URL}/cards/{external_id}"
        headers = {'X-Api-Key': config.TCG_API_KEY} if config.TCG_API_KEY else {}
        
        for attempt in range(retries):
            try:
                if attempt == 0:
                    time.sleep(3)
                else:
                    time.sleep(15 * attempt)
                
                response = requests.get(url, headers=headers, timeout=120)
                
                if response.status_code == 200:
                    card_data = response.json()['data']
                    return self.extract_market_price(card_data)
                elif response.status_code == 404:
                    return None
            except (requests.exceptions.Timeout, Exception):
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return None
        return None

    def fetch_cards_from_database(self, series_name=None):
        """Fetch all unique active UI cards. Allows optional filtering by explicit series."""
        conn = self.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT DISTINCT c.id as card_id, c.external_ids, c.name, c.set_code, c.set_name, c.number, c.img_url
            FROM cards c
            INNER JOIN products p ON p.card_id = c.id
            INNER JOIN variants v ON v.product_id = p.id
            WHERE p.shopify_product_id IS NOT NULL 
        """
        params = []
        
        if series_name:
            query += " AND c.set_name = %s"
            params.append(series_name)
            
        query += " ORDER BY c.id"
            
        try:
            cursor.execute(query, tuple(params))
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def update_variants_in_database(self, card_id, base_market_cad, nm_selling_price):
        """Executes the threshold algorithms and applies mathematical variant payouts to PostgreSQL."""
        conn = self.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        updated_variants = []
        
        try:
            cursor.execute("""
                SELECT v.id, v.condition, v.price_cad, v.market_price, 
                       v.buy_cash, v.buy_credit, v.shopify_variant_id
                FROM variants v
                INNER JOIN products p ON p.id = v.product_id
                WHERE p.card_id = %s
            """, (card_id,))
            
            variants = cursor.fetchall()
            condition_multipliers = {'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35}
            nm_buy_cash, nm_buy_credit = self.calculate_buylist_prices(base_market_cad, 'NM')
            
            for variant in variants:
                condition = variant['condition']
                old_price = float(variant['price_cad']) if variant['price_cad'] else 0
                
                new_price = nm_selling_price if condition == 'NM' else round(nm_selling_price * condition_multipliers.get(condition, 1.0), 2)
                
                if condition in ['NM', 'LP', 'MP']:
                    new_buy_cash, new_buy_credit = self.calculate_buylist_prices(
                        base_market_cad, condition, nm_buy_cash, nm_buy_credit
                    )
                else:
                    new_buy_cash, new_buy_credit = None, None
                
                if self.should_update_price(old_price, new_price):
                    cursor.execute("""
                        UPDATE variants
                        SET market_price = %s, price_cad = %s, buy_cash = %s, buy_credit = %s,
                            price_updated_at = NOW(), updated_at = NOW()
                        WHERE id = %s
                    """, (base_market_cad, new_price, new_buy_cash, new_buy_credit, variant['id']))
                    
                    updated_variants.append({
                        'variant_id': variant['id'],
                        'shopify_variant_id': variant['shopify_variant_id'],
                        'condition': condition,
                        'old_price': old_price,
                        'new_price': new_price,
                        'change': new_price - old_price,
                        'change_percent': ((new_price - old_price) / old_price * 100) if old_price > 0 else 0
                    })
            conn.commit()
            return updated_variants
        except Exception as e:
            conn.rollback()
            return []
        finally:
            cursor.close()
            conn.close()

    def update_shopify_prices(self, updated_variants):
        if not config.SHOPIFY_ACCESS_TOKEN:
            return 0
            
        success_count = 0
        shop_url = config.SHOPIFY_SHOP_URL
        if shop_url and not shop_url.startswith('https://'):
            shop_url = f"https://{shop_url}"
            
        for variant in updated_variants:
            if not variant['shopify_variant_id']:
                continue
            
            try:
                url = f"{shop_url}/admin/api/{config.SHOPIFY_API_VERSION}/variants/{variant['shopify_variant_id']}.json"
                response = requests.put(
                    url,
                    json={"variant": {"id": int(variant['shopify_variant_id']), "price": str(variant['new_price'])}},
                    headers={"X-Shopify-Access-Token": config.SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"},
                    timeout=10
                )
                if response.status_code == 200:
                    success_count += 1
                time.sleep(0.3)
            except Exception:
                continue
                
        return success_count
