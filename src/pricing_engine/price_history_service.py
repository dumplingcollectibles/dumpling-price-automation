from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from src.config import config
from src.pricing_engine.pricing_config import pricing_config

class PriceHistoryService:
    """
    Handles logging daily pricing snapshots to history and analytical 
    comparison over previous intervals (Weekly reporting).
    """

    @staticmethod
    def get_db_connection():
        return psycopg2.connect(config.DATABASE_URL)

    def snapshot_daily_prices(self):
        """Copies current store prices into price_history"""
        conn = self.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT c.id as card_id, c.name as card_name, c.set_code, c.set_name, c.number,
                       v.condition, v.price_cad
                FROM cards c
                JOIN products p ON p.card_id = c.id
                JOIN variants v ON v.product_id = p.id
                WHERE v.inventory_qty > 0 AND c.language = 'English' AND v.price_cad > 0
            """)
            cards = cursor.fetchall()
            if not cards:
                return {'tracked': 0, 'updated': 0, 'errors': 0}
                
            tracked, updated, errors = 0, 0, 0
            
            for card in cards:
                try:
                    price_cad = float(card['price_cad'])
                    market_price_cad = price_cad / config.MARKUP
                    market_price_usd = market_price_cad / config.USD_TO_CAD
                    suggested_price_cad = market_price_cad * config.MARKUP
                    
                    cursor.execute("""
                        SELECT id FROM price_history 
                        WHERE card_id = %s AND condition = %s AND DATE(checked_at) = CURRENT_DATE
                    """, (card['card_id'], card['condition']))
                    existing = cursor.fetchone()
                    
                    if existing:
                        cursor.execute("""
                            UPDATE price_history SET market_price_usd = %s, market_price_cad = %s, 
                            suggested_price_cad = %s, card_name = %s, set_name = %s, checked_at = NOW()
                            WHERE id = %s
                        """, (market_price_usd, market_price_cad, suggested_price_cad, card['card_name'], card['set_name'], existing['id']))
                        updated += 1
                    else:
                        cursor.execute("""
                            INSERT INTO price_history (card_id, condition, market_price_usd, market_price_cad, 
                                suggested_price_cad, card_name, set_name, source, checked_at) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (card['card_id'], card['condition'], market_price_usd, market_price_cad, suggested_price_cad, card['card_name'], card['set_name'], 'database_copy'))
                        tracked += 1
                except Exception:
                    errors += 1
                    conn.rollback()
                    continue
                    
            conn.commit()
            return {'tracked': tracked, 'updated': updated, 'errors': errors}
        finally:
            cursor.close()
            conn.close()

    def get_latest_inventory_prices(self):
        conn = self.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("""
                WITH latest_prices AS (
                    SELECT DISTINCT ON (card_id, condition) card_id, condition, suggested_price_cad, checked_at
                    FROM price_history ORDER BY card_id, condition, checked_at DESC
                )
                SELECT c.id as card_id, c.name as card_name, c.set_code, c.set_name, c.number,
                       v.condition, v.inventory_qty, v.price_cad as current_shopify_price,
                       lp.suggested_price_cad as latest_suggested
                FROM cards c
                JOIN products p ON p.card_id = c.id
                JOIN variants v ON v.product_id = p.id
                LEFT JOIN latest_prices lp ON lp.card_id = c.id AND lp.condition = v.condition
                WHERE v.inventory_qty > 0 AND c.language = 'English'
            """)
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def get_price_at_date(self, card_id, condition, target_date):
        conn = self.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute("""
                SELECT suggested_price_cad, checked_at FROM price_history
                WHERE card_id = %s AND condition = %s AND checked_at <= %s
                ORDER BY checked_at DESC LIMIT 1
            """, (card_id, condition, target_date))
            return cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

    def calculate_weekly_changes(self):
        """Analyzes price changes over 7 days for current inventory"""
        seven_days_ago = datetime.now() - timedelta(days=7)
        cards = self.get_latest_inventory_prices()
        
        drops, increases, no_changes, no_history = [], [], [], []
        
        for card in cards:
            old_data = self.get_price_at_date(card['card_id'], card['condition'], seven_days_ago)
            if not old_data or not card['latest_suggested']:
                no_history.append(card)
                continue
                
            old_price = float(old_data['suggested_price_cad'])
            new_price = float(card['latest_suggested'])
            diff = new_price - old_price
            diff_pct = (diff / old_price * 100) if old_price > 0 else 0
            
            is_significant = abs(diff_pct) >= pricing_config.REPORTING_MIN_CHANGE_PERCENT or abs(diff) >= pricing_config.REPORTING_MIN_CHANGE_DOLLARS
            if not is_significant:
                no_changes.append(card)
                continue
                
            record = {**card, 'old_price': old_price, 'new_price': new_price, 'price_diff': diff, 'price_diff_percent': diff_pct}
            (drops if diff < 0 else increases).append(record)
            
        return {
            'price_drops': sorted(drops, key=lambda x: x['price_diff']),
            'price_increases': sorted(increases, key=lambda x: x['price_diff'], reverse=True),
            'no_changes': no_changes,
            'no_history': no_history,
            'total_checked': len(cards),
            'comparison_date': seven_days_ago
        }
