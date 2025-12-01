"""
PRICE UPDATE SCRIPT v1.0 - Daily Automated Price Sync

Features:
- Fetches latest prices from PokémonTCG API
- Only updates if price changed by 5% AND $0.50 minimum
- Updates database + Shopify
- Email report via Zoho Mail
- Optimized for 445 cards / 2225 variants
- Batch processing: 50 cards at a time

Usage:
  python price_update.py
"""

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import time
import math
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

load_dotenv()

# Database & API Config
DATABASE_URL = os.getenv('NEON_DB_URL')
POKEMONTCG_API_URL = os.getenv('POKEMONTCG_API_URL', 'https://api.pokemontcg.io/v2')
TCG_API_KEY = os.getenv('TCG_API_KEY')

# Shopify Config
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"

# Email Config (Zoho)
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
ZOHO_EMAIL = os.getenv('ZOHO_EMAIL')  # your-email@yourdomain.com
ZOHO_PASSWORD = os.getenv('ZOHO_APP_PASSWORD')  # App password from Zoho
EMAIL_TO = os.getenv('EMAIL_TO', ZOHO_EMAIL)  # Where to send reports

# Pricing Config
USD_TO_CAD = 1.35
MARKUP = 1.10

# Price Change Thresholds
MIN_CHANGE_DOLLARS = 0.50  # Must change by at least $0.50
MIN_CHANGE_PERCENT = 5.0    # AND at least 5%

# Big Change Highlights (for email report)
BIG_CHANGE_PERCENT = 20.0   # 20% or more
BIG_CHANGE_DOLLARS = 10.0   # AND at least $10

# Processing Config - PARALLEL MODE (3 threads)
BATCH_SIZE = 100   # Maximum batches
API_DELAY = 1      # Minimal wait between batches
NUM_THREADS = 3    # Process 3 price buckets simultaneously

# Thread-safe lock for Shopify updates
shopify_lock = threading.Lock()


def round_up_to_nearest_50_cents(amount):
    return math.ceil(amount * 2) / 2


def extract_market_price(api_card):
    """Extract market price from API response"""
    tcgplayer = api_card.get('tcgplayer', {})
    prices = tcgplayer.get('prices', {})
    for price_type in ['normal', 'holofoil', 'reverseHolofoil', 'unlimitedHolofoil']:
        if price_type in prices:
            price_data = prices[price_type]
            market = price_data.get('market') or price_data.get('mid') or price_data.get('low')
            if market and market > 0:
                return float(market)
    return None


def calculate_buylist_prices(market_price, condition, nm_buy_cash=None, nm_buy_credit=None):
    """Calculate buylist prices based on market price and condition"""
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


def should_update_price(old_price, new_price):
    """
    Determine if price should be updated
    Requires BOTH conditions:
    - At least 5% change AND
    - At least $0.50 change
    """
    if old_price == 0 or old_price is None:
        return True  # Always update if no previous price
    
    dollar_change = abs(new_price - old_price)
    percent_change = (dollar_change / old_price) * 100
    
    # BOTH conditions must be met
    return dollar_change >= MIN_CHANGE_DOLLARS and percent_change >= MIN_CHANGE_PERCENT


def is_big_change(old_price, new_price):
    """Check if this is a 'big' price change for highlighting"""
    if old_price == 0 or old_price is None:
        return False
    
    dollar_change = abs(new_price - old_price)
    percent_change = (dollar_change / old_price) * 100
    
    return dollar_change >= BIG_CHANGE_DOLLARS and percent_change >= BIG_CHANGE_PERCENT


def fetch_cards_from_database():
    """Fetch all unique cards from database that need price updates"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get all unique cards with their external IDs
        cursor.execute("""
            SELECT DISTINCT
                c.id as card_id,
                c.external_ids,
                c.name,
                c.set_code,
                c.set_name,
                c.number,
                c.img_url
            FROM cards c
            INNER JOIN products p ON p.card_id = c.id
            INNER JOIN variants v ON v.product_id = p.id
            WHERE p.shopify_product_id IS NOT NULL  -- Only cards in Shopify
            ORDER BY c.id
        """)
        
        cards = cursor.fetchall()
        return cards
    
    finally:
        cursor.close()
        conn.close()


def fetch_api_price(external_id, retries=5):
    """Fetch latest price from API with retry logic - VERY SLOW but RELIABLE"""
    url = f"{POKEMONTCG_API_URL}/cards/{external_id}"
    headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
    
    for attempt in range(retries):
        try:
            # Always wait before making request (be very nice to API)
            if attempt == 0:
                time.sleep(3)  # 3 second delay before first attempt
            else:
                wait_time = 15 * attempt  # 15s, 30s, 45s, 60s
                print(f" (retry {attempt+1}/{retries}, waiting {wait_time}s)...", end='', flush=True)
                time.sleep(wait_time)
            
            response = requests.get(url, headers=headers, timeout=120)  # Increased to 120s
            
            if response.status_code == 200:
                card_data = response.json()['data']
                market_usd = extract_market_price(card_data)
                return market_usd
            elif response.status_code == 404:
                return None  # Card not found
            
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                time.sleep(5)  # Wait before retry
                continue
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            return None
    
    return None


def update_variants_in_database(card_id, base_market_cad, nm_selling_price):
    """Update all variants for a card in the database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    updated_variants = []
    
    try:
        # Get all variants for this card
        cursor.execute("""
            SELECT v.id, v.condition, v.price_cad, v.market_price, 
                   v.buy_cash, v.buy_credit, v.shopify_variant_id
            FROM variants v
            INNER JOIN products p ON p.id = v.product_id
            WHERE p.card_id = %s
        """, (card_id,))
        
        variants = cursor.fetchall()
        
        # Calculate new prices for each condition
        condition_multipliers = {'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35}
        nm_buy_cash, nm_buy_credit = calculate_buylist_prices(base_market_cad, 'NM')
        
        for variant in variants:
            condition = variant['condition']
            old_price = float(variant['price_cad']) if variant['price_cad'] else 0
            
            # Calculate new selling price
            if condition == 'NM':
                new_price = nm_selling_price
            else:
                new_price = round(nm_selling_price * condition_multipliers[condition], 2)
            
            # Calculate new buylist prices
            if condition in ['NM', 'LP', 'MP']:
                new_buy_cash, new_buy_credit = calculate_buylist_prices(
                    base_market_cad, condition, nm_buy_cash, nm_buy_credit
                )
            else:
                new_buy_cash, new_buy_credit = None, None
            
            # Check if we should update
            if should_update_price(old_price, new_price):
                cursor.execute("""
                    UPDATE variants
                    SET market_price = %s,
                        price_cad = %s,
                        buy_cash = %s,
                        buy_credit = %s,
                        price_updated_at = NOW(),
                        updated_at = NOW()
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
        print(f"      ❌ Database error: {str(e)[:100]}")
        return []
    finally:
        cursor.close()
        conn.close()


def update_shopify_prices(updated_variants):
    """Update prices in Shopify for all updated variants"""
    if not SHOPIFY_ACCESS_TOKEN:
        return 0
    
    success_count = 0
    
    for variant in updated_variants:
        if not variant['shopify_variant_id']:
            continue
        
        try:
            url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{variant['shopify_variant_id']}.json"
            
            response = requests.put(
                url,
                json={"variant": {"id": int(variant['shopify_variant_id']), "price": str(variant['new_price'])}},
                headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                success_count += 1
            
            time.sleep(0.3)  # Ultra-fast mode - 0.3 second (was 0.5)
            
        except Exception as e:
            continue
    
    return success_count


def send_email_report(report_data):
    """Send email report via Zoho Mail"""
    if not EMAIL_ENABLED or not ZOHO_EMAIL or not ZOHO_PASSWORD:
        print("\n📧 Email disabled or not configured")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Price Update Report - {report_data['date']}"
        msg['From'] = ZOHO_EMAIL
        msg['To'] = EMAIL_TO
        
        # Create email body
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
                .summary {{ background: #f5f5f5; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                .stat {{ display: inline-block; margin: 10px 20px; }}
                .stat-value {{ font-size: 24px; font-weight: bold; color: #4CAF50; }}
                .stat-label {{ font-size: 12px; color: #666; }}
                .section {{ margin: 20px 0; }}
                .card {{ background: white; border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }}
                .price-up {{ color: #e74c3c; }}
                .price-down {{ color: #27ae60; }}
                .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>💰 Dumpling Collectibles - Price Update Report</h1>
                <p>{report_data['date']}</p>
            </div>
            
            <div class="summary">
                <div class="stat">
                    <div class="stat-value">{report_data['total_processed']}</div>
                    <div class="stat-label">Cards Processed</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{report_data['total_updated']}</div>
                    <div class="stat-label">Cards Updated</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{report_data['variants_updated']}</div>
                    <div class="stat-label">Variants Updated</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{report_data['shopify_synced']}</div>
                    <div class="stat-label">Shopify Synced</div>
                </div>
            </div>
            
            <div class="section">
                <h2>📊 Summary</h2>
                <ul>
                    <li>Price increases: {report_data['price_increases']}</li>
                    <li>Price decreases: {report_data['price_decreases']}</li>
                    <li>Failed updates: {report_data['failed']}</li>
                    <li>No change needed: {report_data['no_change']}</li>
                </ul>
            </div>
            
            <div class="section">
                <h2>💎 Biggest Price Changes</h2>
        """
        
        if report_data['big_changes']:
            for change in report_data['big_changes'][:10]:  # Top 10
                direction = "↗️" if change['change'] > 0 else "↘️"
                color_class = "price-up" if change['change'] > 0 else "price-down"
                html += f"""
                <div class="card">
                    <strong>{direction} {change['name']}</strong> (#{change['number']})
                    <br>
                    <span class="{color_class}">
                        ${change['old_price']:.2f} → ${change['new_price']:.2f} 
                        ({change['change']:+.2f} / {change['change_percent']:+.1f}%)
                    </span>
                </div>
                """
        else:
            html += "<p>No significant price changes (20%+ and $10+)</p>"
        
        html += """
            </div>
            
            <div class="footer">
                <p>Automated by Dumpling Collectibles Price Update System</p>
                <p>Run time: """ + report_data['run_time'] + """</p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        # Send via Zoho SMTP
        with smtplib.SMTP('smtp.zoho.com', 587) as server:
            server.starttls()
            server.login(ZOHO_EMAIL, ZOHO_PASSWORD)
            server.send_message(msg)
        
        print("\n✅ Email report sent successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to send email: {str(e)}")
        return False


def process_card_group(cards, group_name, stats_dict):
    """Process a group of cards (for parallel execution)"""
    local_stats = {
        'total_processed': 0,
        'total_updated': 0,
        'variants_updated': 0,
        'shopify_synced': 0,
        'price_increases': 0,
        'price_decreases': 0,
        'failed': 0,
        'no_change': 0,
        'big_changes': []
    }
    
    print(f"\n🧵 Thread '{group_name}' starting with {len(cards)} cards...")
    
    for i, card in enumerate(cards, 1):
        local_stats['total_processed'] += 1
        
        # Progress update
        print(f"   [{group_name}] [{i}/{len(cards)}] {card['name']} ({card['set_code']}-{card['number']})...", end=' ', flush=True)
        
        # Get external ID
        external_ids = card['external_ids']
        pokemontcg_id = external_ids.get('pokemontcg_io') if external_ids else None
        
        if not pokemontcg_id:
            local_stats['failed'] += 1
            print(f" ❌ No API ID")
            continue
        
        # Fetch latest price from API
        market_usd = fetch_api_price(pokemontcg_id)
        
        if market_usd is None:
            local_stats['failed'] += 1
            print(f" ❌ API failed")
            continue
        
        # Calculate new prices
        base_market_cad = market_usd * USD_TO_CAD
        nm_selling_price = round_up_to_nearest_50_cents(base_market_cad * MARKUP)
        
        # Update database
        updated_variants = update_variants_in_database(
            card['card_id'], 
            base_market_cad, 
            nm_selling_price
        )
        
        if updated_variants:
            local_stats['total_updated'] += 1
            local_stats['variants_updated'] += len(updated_variants)
            
            # Update Shopify (with thread lock for rate limiting)
            with shopify_lock:
                shopify_success = update_shopify_prices(updated_variants)
                local_stats['shopify_synced'] += shopify_success
            
            # Track increases/decreases
            for variant in updated_variants:
                if variant['change'] > 0:
                    local_stats['price_increases'] += 1
                else:
                    local_stats['price_decreases'] += 1
                
                # Check for big changes
                if is_big_change(variant['old_price'], variant['new_price']):
                    local_stats['big_changes'].append({
                        'name': card['name'],
                        'number': card['number'],
                        'condition': variant['condition'],
                        'old_price': variant['old_price'],
                        'new_price': variant['new_price'],
                        'change': variant['change'],
                        'change_percent': variant['change_percent']
                    })
            
            print(f" ✅ Updated {len(updated_variants)} variants")
        else:
            local_stats['no_change'] += 1
            print(f" ⏭️  No change")
        
        # Minimal delay
        time.sleep(0.5)
    
    print(f"\n✅ Thread '{group_name}' completed: {local_stats['total_updated']} cards updated")
    return local_stats


def merge_stats(stats_list):
    """Merge statistics from multiple threads"""
    merged = {
        'total_processed': 0,
        'total_updated': 0,
        'variants_updated': 0,
        'shopify_synced': 0,
        'price_increases': 0,
        'price_decreases': 0,
        'failed': 0,
        'no_change': 0,
        'big_changes': []
    }
    
    for stats in stats_list:
        merged['total_processed'] += stats['total_processed']
        merged['total_updated'] += stats['total_updated']
        merged['variants_updated'] += stats['variants_updated']
        merged['shopify_synced'] += stats['shopify_synced']
        merged['price_increases'] += stats['price_increases']
        merged['price_decreases'] += stats['price_decreases']
        merged['failed'] += stats['failed']
        merged['no_change'] += stats['no_change']
        merged['big_changes'].extend(stats['big_changes'])
    
    return merged


def main():
    """Main price update process - PARALLEL VERSION"""
    start_time = datetime.now()
    
    print("=" * 100)
    print("💰 PRICE UPDATE SCRIPT - PARALLEL MODE (3 Threads)")
    print("=" * 100)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Thresholds: 5% change AND $0.50 minimum")
    print(f"Threads: {NUM_THREADS} (processing price buckets simultaneously)\n")
    
    # Step 1: Fetch cards from database
    print("📚 Step 1: Fetching cards from database...")
    cards = fetch_cards_from_database()
    print(f"   ✅ Found {len(cards)} cards to check\n")
    
    # Step 2: Split cards into price buckets for parallel processing
    print("🗂️  Step 2: Splitting cards into price buckets...")
    
    # Get current market prices for bucketing
    cards_with_prices = []
    for card in cards:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT market_price 
            FROM variants v
            INNER JOIN products p ON p.id = v.product_id
            WHERE p.card_id = %s AND v.condition = 'NM'
            LIMIT 1
        """, (card['card_id'],))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        price = float(result['market_price']) if result and result['market_price'] else 0
        cards_with_prices.append((card, price))
    
    # Split into 3 buckets
    cards_low = [card for card, price in cards_with_prices if price < 10]
    cards_mid = [card for card, price in cards_with_prices if 10 <= price <= 50]
    cards_high = [card for card, price in cards_with_prices if price > 50]
    
    print(f"   💵 Low tier (< $10): {len(cards_low)} cards")
    print(f"   💰 Mid tier ($10-$50): {len(cards_mid)} cards")
    print(f"   💎 High tier (> $50): {len(cards_high)} cards")
    print(f"   📊 Total: {len(cards)} cards\n")
    
    # Step 3: Process in parallel
    print(f"⚡ Step 3: Processing {NUM_THREADS} price buckets in parallel...\n")
    
    # Create thread pool and submit jobs
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_low = executor.submit(process_card_group, cards_low, "LOW-TIER", None)
        future_mid = executor.submit(process_card_group, cards_mid, "MID-TIER", None)
        future_high = executor.submit(process_card_group, cards_high, "HIGH-TIER", None)
        
        # Wait for all threads to complete
        stats_low = future_low.result()
        stats_mid = future_mid.result()
        stats_high = future_high.result()
    
    # Merge statistics from all threads
    stats = merge_stats([stats_low, stats_mid, stats_high])
    
    print("\n" + "=" * 100)
    print("⚡ PARALLEL PROCESSING COMPLETE!")
    print("=" * 100)
    
    # Step 4: Generate report
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print("\n" + "=" * 100)
    print("📊 PRICE UPDATE COMPLETE!")
    print("=" * 100)
    print(f"Cards processed:     {stats['total_processed']}")
    print(f"Cards updated:       {stats['total_updated']}")
    print(f"Variants updated:    {stats['variants_updated']}")
    print(f"Shopify synced:      {stats['shopify_synced']}")
    print(f"Price increases:     {stats['price_increases']}")
    print(f"Price decreases:     {stats['price_decreases']}")
    print(f"No change needed:    {stats['no_change']}")
    print(f"Failed:              {stats['failed']}")
    print(f"Big changes (20%+):  {len(stats['big_changes'])}")
    print(f"\n⏱️  Total time: {duration:.1f} seconds")
    print("=" * 100)
    
    # Send email report
    if EMAIL_ENABLED:
        report_data = {
            'date': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_processed': stats['total_processed'],
            'total_updated': stats['total_updated'],
            'variants_updated': stats['variants_updated'],
            'shopify_synced': stats['shopify_synced'],
            'price_increases': stats['price_increases'],
            'price_decreases': stats['price_decreases'],
            'failed': stats['failed'],
            'no_change': stats['no_change'],
            'big_changes': sorted(stats['big_changes'], key=lambda x: abs(x['change_percent']), reverse=True),
            'run_time': f"{duration:.1f} seconds"
        }
        send_email_report(report_data)


if __name__ == "__main__":
    main()
