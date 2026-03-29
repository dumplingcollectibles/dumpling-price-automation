import psycopg2
from psycopg2.extras import RealDictCursor, Json
import requests
import math
import logging
from datetime import datetime
from difflib import SequenceMatcher
from src.config import config
from src.inventory.inventory_config import inventory_config

logger = logging.getLogger(__name__)

class InventoryService:
    """
    Business Logic Service for Dumpling Collectibles Inventory Management.
    Handles searching, quantity updates, WAC calculation, Shopify sync, 
    and transaction audit logs.
    """

    def __init__(self, db_conn=None):
        self.conn = db_conn or psycopg2.connect(config.DATABASE_URL)

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

    def search_cards(self, query, limit=20):
        """Unified database search for cards."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id as card_id, name, set_code, set_name, number, variant, language
            FROM cards WHERE name ILIKE %s ORDER BY name, set_code, number LIMIT %s
        """, (f"%{query}%", limit))
        return cursor.fetchall()

    def find_set_suggestion(self, set_code):
        """Fuzzy searches for set codes in the database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT set_code FROM cards")
        all_sets = [r[0] for r in cursor.fetchall()]
        
        best_match, best_score = None, 0
        for s in all_sets:
            score = SequenceMatcher(None, set_code.lower(), s.lower()).ratio()
            if score > best_score:
                best_match, best_score = s, score
        return best_match if best_score >= 0.7 else None

    def find_card_exact(self, name, set_code, number):
        """Finds a card ID using exact set/number criteria and fuzzy name matching."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name FROM cards WHERE set_code = %s AND number = %s LIMIT 1", (set_code, str(number)))
        result = cursor.fetchone()
        
        if result:
            score = SequenceMatcher(None, name.lower(), result['name'].lower()).ratio()
            return result['id'], result['name'], score
        return None, None, 0

    def fetch_card_from_api(self, set_code, number):
        """Retrieves real-time card data and TCGplayer pricing from the PokémonTCG API."""
        url = f"{config.POKEMONTCG_API_URL}/cards"
        params = {"q": f"set.id:{set_code} number:{number}"}
        headers = {'X-Api-Key': config.TCG_API_KEY} if config.TCG_API_KEY else {}
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                cards = resp.json().get('data', [])
                return cards[0] if cards else None
        except Exception as e:
            logger.error(f"API Fetch Error: {e}")
        return None

    def extract_market_price(self, api_card):
        """Heuristic for determining current USD market price from API response."""
        prices = api_card.get('tcgplayer', {}).get('prices', {})
        for pt in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil']:
            if pt in prices:
                m = prices[pt].get('market') or prices[pt].get('mid')
                if m: return float(m)
        return 0.50 # Default baseline

    def create_card_record(self, api_card, market_price_usd):
        """
        Orchestrates full database record creation for a new card.
        Initializes: 1 Card + 1 Product + 5 Variants (NM through DMG).
        """
        cursor = self.conn.cursor()
        try:
            base_cad = market_price_usd * inventory_config.USD_TO_CAD
            nm_price = math.ceil(base_cad * inventory_config.MARKUP * 2) / 2 # Round to nearest 0.50
            
            # 1. Insert Card
            cursor.execute("""
                INSERT INTO cards (external_ids, name, set_code, set_name, number, variant, language, rarity, supertype, img_url, release_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name, set_code, number, variant, language) DO UPDATE SET updated_at = NOW()
                RETURNING id
            """, (
                Json({'pokemontcg_io': api_card['id']}), api_card['name'], api_card['set']['id'],
                api_card['set']['name'], api_card['number'], 'Normal', 'English',
                api_card.get('rarity', 'Unknown'), api_card.get('supertype', 'Unknown'),
                api_card['images']['large'], api_card['set']['releaseDate']
            ))
            card_id = cursor.fetchone()[0]

            # 2. Insert Product (Handle generation)
            handle = f"{api_card['name']}-{api_card['set']['id']}-{api_card['number']}".lower().replace(' ', '-').replace("'", '')
            cursor.execute("""
                INSERT INTO products (card_id, handle, product_type, status, tags)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id
            """, (card_id, handle, 'Single', 'draft', [api_card['set']['name'], api_card['name']]))
            product_id = cursor.fetchone()[0] if cursor.rowcount > 0 else None
            
            if not product_id:
                cursor.execute("SELECT id FROM products WHERE card_id = %s", (card_id,))
                product_id = cursor.fetchone()[0]

            # 3. Insert Variants
            for cond in inventory_config.VALID_CONDITIONS:
                sku = f"{api_card['set']['id'].upper()}-{api_card['number']}-{cond}"
                mult = inventory_config.CONDITION_MULTIPLIERS.get(cond, 1.0)
                selling_price = nm_price if cond == 'NM' else round(nm_price * mult, 2)
                
                cursor.execute("""
                    INSERT INTO variants (product_id, condition, sku, inventory_qty, market_price, price_cad)
                    VALUES (%s, %s, %s, 0, %s, %s) ON CONFLICT (sku) DO NOTHING
                """, (product_id, cond, sku, base_cad, selling_price))

            self.conn.commit()
            return card_id
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def get_variant_info(self, card_id, condition):
        """Fetches full variant state including current inventory and Shopify IDs."""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT v.*, c.name, c.set_code, c.number
            FROM variants v
            JOIN products p ON p.id = v.product_id
            JOIN cards c ON c.id = p.card_id
            WHERE p.card_id = %s AND v.condition = %s
        """, (card_id, condition.upper()))
        return cursor.fetchone()

    def update_quantity(self, variant_id, delta, unit_cost=None, source='other', notes=None, transaction_type='adjustment'):
        """
        Primary engine for changing internal inventory counts.
        Handles WAC calculation, Shopify sync, and database transaction consistency.
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            # 1. Capture current state
            cursor.execute("SELECT inventory_qty, cost_basis_avg, total_units_purchased, shopify_variant_id FROM variants WHERE id = %s", (variant_id,))
            v = cursor.fetchone()
            if not v: return False
            
            old_qty = v['inventory_qty']
            new_qty = old_qty + delta
            
            # 2. Update WAC only on purchases/additions
            new_wac = v['cost_basis_avg']
            new_total_units = (v['total_units_purchased'] or 0)
            if delta > 0 and unit_cost is not None:
                new_total_units += delta
                if v['cost_basis_avg'] is None or old_qty == 0:
                    new_wac = unit_cost
                else:
                    new_wac = round(((old_qty * float(v['cost_basis_avg'])) + (delta * unit_cost)) / (old_qty + delta), 2)

            # 3. Update Database
            cursor.execute("""
                UPDATE variants SET inventory_qty = %s, cost_basis_avg = %s, total_units_purchased = %s, updated_at = NOW()
                WHERE id = %s
            """, (new_qty, new_wac, new_total_units, variant_id))
            
            # 4. Audit Log
            cursor.execute("""
                INSERT INTO inventory_transactions (variant_id, transaction_type, quantity, unit_cost, reference_type, notes, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (variant_id, transaction_type, delta, unit_cost, 'inventory_service', notes))
            
            self.conn.commit()
            
            # 5. Shopify Sync
            if v['shopify_variant_id']:
                self.sync_to_shopify(v['shopify_variant_id'], new_qty)
            
            return True
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def sync_to_shopify(self, shopify_variant_id, new_qty):
        """Asynchronously (or synchronously) updates Shopify location balance."""
        if not config.SHOPIFY_ACCESS_TOKEN or not config.SHOPIFY_LOCATION_ID:
            return False
            
        try:
            # Fetch inventory item ID
            v_url = f"https://{config.SHOPIFY_SHOP_URL}/admin/api/{config.SHOPIFY_API_VERSION}/variants/{shopify_variant_id}.json"
            v_resp = requests.get(v_url, headers={"X-Shopify-Access-Token": config.SHOPIFY_ACCESS_TOKEN}, timeout=10)
            if v_resp.status_code != 200: return False
            
            item_id = v_resp.json()['variant']['inventory_item_id']
            # Set level
            l_url = f"https://{config.SHOPIFY_SHOP_URL}/admin/api/{config.SHOPIFY_API_VERSION}/inventory_levels/set.json"
            l_resp = requests.post(l_url, json={
                "location_id": int(config.SHOPIFY_LOCATION_ID), "inventory_item_id": item_id, "available": new_qty
            }, headers={"X-Shopify-Access-Token": config.SHOPIFY_ACCESS_TOKEN}, timeout=10)
            return l_resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Shopify Sync Failed: {e}")
            return False

    def validate_condition(self, condition):
        """Canonicalizes condition strings using fuzzy domain rules."""
        c = str(condition).upper().strip()
        if c in inventory_config.VALID_CONDITIONS:
            return True, c, None
        
        # Check variations
        if c in inventory_config.CONDITION_VARIATIONS:
            mapped = inventory_config.CONDITION_VARIATIONS[c]
            return True, mapped, f"Auto-corrected '{condition}' -> '{mapped}'"
        
        return False, None, f"Invalid condition: '{condition}'"

    def validate_source(self, source):
        """Canonicalizes transaction source strings."""
        s = str(source).lower().strip()
        if s in inventory_config.VALID_SOURCES_ADD:
            return True, s, None
        
        if s in inventory_config.SOURCE_MAPPINGS:
            mapped = inventory_config.SOURCE_MAPPINGS[s]
            return True, mapped, f"Auto-corrected source '{source}' -> '{mapped}'"
            
        return False, None, f"Invalid source: '{source}'"

    def validate_row(self, row):
        """
        Deep validation of a single CSV row.
        Executes schema checks, db-state lookups, and fuzzy string resolution.
        """
        errors, warnings, corrections = [], [], {}
        required = ['card_name', 'set_code', 'card_number', 'condition', 'quantity', 'unit_cost', 'source']
        
        # Basic Schema
        for f in required:
            if not str(row.get(f, '')).strip():
                errors.append(f"Missing field: {f}")
        if errors: return False, warnings, errors, corrections

        # 1. Condition & Source
        valid_c, cond, msg_c = self.validate_condition(row['condition'])
        if not valid_c: errors.append(msg_c)
        else: 
            corrections['condition'] = cond
            if msg_c: warnings.append(msg_c)

        valid_s, src, msg_s = self.validate_source(row['source'])
        if not valid_s: errors.append(msg_s)
        else:
            corrections['source'] = src
            if msg_s: warnings.append(msg_s)

        # 2. Database Lookup
        card_id, actual_name, score = self.find_card_exact(row['card_name'], row['set_code'], row['card_number'])
        if card_id:
            corrections['card_id'] = card_id
            if score < 1.0:
                warnings.append(f"Fuzzy-matched name: '{row['card_name']}' -> '{actual_name}'")
        else:
            suggestion = self.find_set_suggestion(row['set_code'])
            if suggestion:
                errors.append(f"Set '{row['set_code']}' not found. Did you mean '{suggestion}'?")
            else:
                warnings.append(f"Card '{row['card_name']}' not in DB. Will API fetch.")
                corrections['needs_api_fetch'] = True

        # 3. Numeric Types
        try:
            corrections['quantity'] = int(row['quantity'])
            if corrections['quantity'] <= 0: errors.append("Qty must be > 0")
        except ValueError: errors.append("Qty must be numeric")

        try:
            corrections['unit_cost'] = float(row['unit_cost'])
            if corrections['unit_cost'] < 0: errors.append("Cost cannot be negative")
        except ValueError: errors.append("Cost must be numeric")

        return len(errors) == 0, warnings, errors, corrections
