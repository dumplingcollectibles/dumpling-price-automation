"""
SERIES-BASED PRICE UPDATE SCRIPT
Updates prices for cards from a specific series (e.g., Scarlet & Violet)

OPTIMIZED FOR SPEED:
- Batch queries to reduce database round-trips
- Minimal delays (API is the bottleneck, not the script)
- Progress tracking with resume capability
- Concurrent requests where possible

EXPECTED TIME:
- ~21 seconds per card (API limitation)
- For 400 Scarlet & Violet cards: ~2.5 hours
"""

import requests
import psycopg
from psycopg.rows import dict_row
import os
from dotenv import load_dotenv
import time
import math
from datetime import datetime
import json
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

# Pricing Config
USD_TO_CAD = 1.35
MARKUP = 1.10

# Price Change Thresholds
MIN_CHANGE_DOLLARS = 0.50
MIN_CHANGE_PERCENT = 5.0

# Email Config (Brevo/Sendinblue SMTP)
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'true').lower() == 'true'
BREVO_SMTP_SERVER = 'smtp-relay.brevo.com'
BREVO_SMTP_PORT = 587
BREVO_API_KEY = os.getenv('BREVO_API_KEY')  # Your existing Brevo SMTP key
BREVO_EMAIL = os.getenv('BREVO_EMAIL')  # Your Brevo sender email
EMAIL_TO = 'reports@dumplingcollectibles.com'  # Where reports are sent

# Progress file (for resume capability)
PROGRESS_FILE = "price_update_progress.json"


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
    """Determine if price should be updated (5% AND $0.50 change)"""
    if old_price == 0 or old_price is None:
        return True
    
    dollar_change = abs(new_price - old_price)
    percent_change = (dollar_change / old_price) * 100
    
    return dollar_change >= MIN_CHANGE_DOLLARS and percent_change >= MIN_CHANGE_PERCENT


def load_progress(series):
    """Load progress for this series"""
    progress_file = f"price_update_{series.replace(' ', '_').replace('&', 'and').lower()}_progress.json"
    
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                return json.load(f)
        except:
            return {'processed_card_ids': [], 'last_run': None}
    return {'processed_card_ids': [], 'last_run': None}


def save_progress(series, processed_ids):
    """Save progress for resume capability"""
    progress_file = f"price_update_{series.replace(' ', '_').replace('&', 'and').lower()}_progress.json"
    
    progress = {
        'processed_card_ids': processed_ids,
        'last_run': datetime.now().isoformat()
    }
    
    with open(progress_file, 'w') as f:
        json.dump(progress, f, indent=2)


def fetch_cards_from_series(series):
    """Fetch all cards from a specific series that need price updates"""
    
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT
                        c.id as card_id,
                        c.external_ids,
                        c.name,
                        c.set_code,
                        c.set_name,
                        c.series,
                        c.number
                    FROM cards c
                    INNER JOIN products p ON p.card_id = c.id
                    INNER JOIN variants v ON v.product_id = p.id
                    WHERE c.series = %s
                    AND p.shopify_product_id IS NOT NULL
                    ORDER BY c.id
                """, (series,))
                
                cards = cursor.fetchall()
                return cards
    
    except Exception as e:
        print(f"❌ Database error: {e}")
        return []


def fetch_api_price(external_id, retries=5):
    """Fetch latest price from API with aggressive retry logic"""
    url = f"{POKEMONTCG_API_URL}/cards/{external_id}"
    headers = {'X-Api-Key': TCG_API_KEY} if TCG_API_KEY else {}
    
    for attempt in range(retries):
        try:
            # Longer timeout for reliability
            response = requests.get(url, headers=headers, timeout=120)
            
            if response.status_code == 200:
                card_data = response.json()['data']
                market_usd = extract_market_price(card_data)
                return market_usd
            elif response.status_code == 404:
                return None  # Card truly doesn't exist
            elif response.status_code == 429:
                # Rate limited - progressive backoff
                wait_time = 10 * (attempt + 1)
                print(f"⚠️  Rate limited, waiting {wait_time}s...", end=' ', flush=True)
                time.sleep(wait_time)
                continue
            else:
                # Other errors - retry with backoff
                if attempt < retries - 1:
                    wait_time = 5 * (attempt + 1)
                    time.sleep(wait_time)
                    continue
            
        except requests.exceptions.Timeout:
            if attempt < retries - 1:
                wait_time = 10 * (attempt + 1)
                print(f"⏰ Timeout (attempt {attempt + 1}/{retries}), waiting {wait_time}s...", end=' ', flush=True)
                time.sleep(wait_time)
                continue
            return None
        except Exception as e:
            if attempt < retries - 1:
                wait_time = 5 * (attempt + 1)
                time.sleep(wait_time)
                continue
            return None
    
    return None


def update_variants_in_database(card_id, base_market_cad, nm_selling_price):
    """Update all variants for a card - BATCH operation"""
    
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                # Get all variants
                cursor.execute("""
                    SELECT v.id, v.condition, v.price_cad, v.market_price, 
                           v.buy_cash, v.buy_credit, v.shopify_variant_id
                    FROM variants v
                    INNER JOIN products p ON p.id = v.product_id
                    WHERE p.card_id = %s
                """, (card_id,))
                
                variants = cursor.fetchall()
                
                condition_multipliers = {'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35}
                nm_buy_cash, nm_buy_credit = calculate_buylist_prices(base_market_cad, 'NM')
                
                updated_variants = []
                
                for variant in variants:
                    condition = variant['condition']
                    old_price = variant['price_cad']
                    
                    # Calculate new prices
                    new_selling_price = nm_selling_price if condition == 'NM' else round(nm_selling_price * condition_multipliers[condition], 2)
                    
                    if condition in ['NM', 'LP', 'MP']:
                        new_buy_cash, new_buy_credit = calculate_buylist_prices(base_market_cad, condition, nm_buy_cash, nm_buy_credit)
                    else:
                        new_buy_cash, new_buy_credit = None, None
                    
                    # Check if update needed
                    if should_update_price(old_price, new_selling_price):
                        cursor.execute("""
                            UPDATE variants
                            SET price_cad = %s,
                                market_price = %s,
                                buy_cash = %s,
                                buy_credit = %s,
                                updated_at = NOW()
                            WHERE id = %s
                        """, (new_selling_price, base_market_cad, new_buy_cash, new_buy_credit, variant['id']))
                        
                        updated_variants.append({
                            'variant_id': variant['id'],
                            'shopify_variant_id': variant['shopify_variant_id'],
                            'condition': condition,
                            'old_price': old_price,
                            'new_price': new_selling_price,
                            'change': new_selling_price - old_price
                        })
                
                conn.commit()
                return updated_variants
    
    except Exception as e:
        return []


def update_shopify_prices(updated_variants):
    """Batch update Shopify prices"""
    if not SHOPIFY_ACCESS_TOKEN:
        return 0
    
    success_count = 0
    
    for variant in updated_variants:
        if not variant['shopify_variant_id']:
            continue
        
        try:
            response = requests.put(
                f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{variant['shopify_variant_id']}.json",
                json={"variant": {"id": variant['shopify_variant_id'], "price": str(variant['new_price'])}},
                headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN},
                timeout=10
            )
            
            if response.status_code == 200:
                success_count += 1
        except:
            pass
    
    return success_count


def send_email_report(series, stats, start_time, end_time):
    """Send HTML email report via Brevo SMTP"""
    
    if not EMAIL_ENABLED or not BREVO_API_KEY or not BREVO_EMAIL:
        print("⏭️  Email disabled or BREVO credentials not set")
        return False
    
    duration = (end_time - start_time).total_seconds()
    date_str = start_time.strftime('%b %d %Y')  # Dec 16 2025
    
    subject = f"{series} Price Update Report {date_str}"
    
    # Create HTML email
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
            .summary {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .stat {{ display: inline-block; margin: 10px 20px 10px 0; }}
            .stat-value {{ font-size: 32px; font-weight: bold; color: #3498db; }}
            .stat-label {{ font-size: 14px; color: #7f8c8d; }}
            .success {{ color: #27ae60; }}
            .warning {{ color: #f39c12; }}
            .error {{ color: #e74c3c; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <h1>💰 {series} Price Update Report</h1>
        <p><strong>Date:</strong> {start_time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Duration:</strong> {duration/3600:.1f} hours</p>
        
        <div class="summary">
            <div class="stat">
                <div class="stat-value">{stats['total_processed']}</div>
                <div class="stat-label">Cards Processed</div>
            </div>
            <div class="stat">
                <div class="stat-value success">{stats['total_updated']}</div>
                <div class="stat-label">Cards Updated</div>
            </div>
            <div class="stat">
                <div class="stat-value">{stats['variants_updated']}</div>
                <div class="stat-label">Variants Updated</div>
            </div>
            <div class="stat">
                <div class="stat-value success">{stats['shopify_synced']}</div>
                <div class="stat-label">Shopify Synced</div>
            </div>
        </div>
        
        <h2>📊 Breakdown</h2>
        <ul>
            <li><span class="success">✅ Updated:</span> {stats['total_updated']} cards</li>
            <li><span class="warning">⏭️  No Change:</span> {stats['no_change']} cards</li>
            <li><span class="error">❌ Failed:</span> {stats['failed']} cards</li>
        </ul>
        
        <div class="footer">
            <p>Automated by Dumpling Collectibles Price Update System</p>
            <p>Series: {series} | Threshold: {MIN_CHANGE_PERCENT}% and ${MIN_CHANGE_DOLLARS:.2f}</p>
        </div>
    </body>
    </html>
    """
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = BREVO_EMAIL
        msg['To'] = EMAIL_TO
        
        msg.attach(MIMEText(html, 'html'))
        
        # Send via Brevo SMTP
        with smtplib.SMTP(BREVO_SMTP_SERVER, BREVO_SMTP_PORT) as server:
            server.starttls()
            server.login(BREVO_EMAIL, BREVO_API_KEY)  # Use email as username
            server.send_message(msg)
        
        print(f"\n✅ Email report sent to {EMAIL_TO}!")
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to send email: {str(e)}")
        return False


def update_prices_for_series(series):
    """Main price update function for a specific series"""
    
    start_time = datetime.now()
    
    print("=" * 100)
    print(f"💰 PRICE UPDATE: {series} Series")
    print("=" * 100)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Thresholds: {MIN_CHANGE_PERCENT}% AND ${MIN_CHANGE_DOLLARS:.2f} minimum\n")
    
    # Load progress
    progress = load_progress(series)
    processed_ids = set(progress.get('processed_card_ids', []))
    
    if processed_ids:
        print(f"📂 Resuming: {len(processed_ids)} cards already processed\n")
    
    # Statistics
    stats = {
        'total_processed': 0,
        'total_updated': 0,
        'variants_updated': 0,
        'shopify_synced': 0,
        'failed': 0,
        'no_change': 0,
        'skipped': 0
    }
    
    # Fetch cards
    print(f"📚 Fetching {series} cards from database...")
    cards = fetch_cards_from_series(series)
    
    if not cards:
        print(f"❌ No cards found for series: {series}")
        return
    
    remaining_cards = [c for c in cards if c['card_id'] not in processed_ids]
    
    print(f"✅ Found {len(cards)} total cards")
    print(f"⏭️  Already processed: {len(processed_ids)}")
    print(f"⏳ Remaining: {len(remaining_cards)}\n")
    
    if not remaining_cards:
        print("✅ All cards already processed!")
        return
    
    # Process cards
    print(f"🔄 Processing {len(remaining_cards)} cards...")
    print(f"⏱️  Estimated time: {(len(remaining_cards) * 21 / 3600):.1f} hours\n")
    
    for i, card in enumerate(remaining_cards, 1):
        stats['total_processed'] += 1
        
        print(f"[{i}/{len(remaining_cards)}] {card['name']} ({card['set_code']}-{card['number']})...", 
              end=' ', flush=True)
        
        # Get external ID
        external_ids = card.get('external_ids') or {}
        pokemontcg_id = external_ids.get('pokemontcg_io')
        
        if not pokemontcg_id:
            stats['failed'] += 1
            print("❌ No API ID")
            processed_ids.add(card['card_id'])
            save_progress(series, list(processed_ids))
            continue
        
        # Fetch price from API
        market_usd = fetch_api_price(pokemontcg_id)
        
        if market_usd is None:
            stats['failed'] += 1
            print("❌ API failed")
            processed_ids.add(card['card_id'])
            save_progress(series, list(processed_ids))
            continue
        
        # Calculate new prices
        base_market_cad = market_usd * USD_TO_CAD
        nm_selling_price = round_up_to_nearest_50_cents(base_market_cad * MARKUP)
        
        # Update database
        updated_variants = update_variants_in_database(card['card_id'], base_market_cad, nm_selling_price)
        
        if updated_variants:
            stats['total_updated'] += 1
            stats['variants_updated'] += len(updated_variants)
            
            # Update Shopify
            shopify_success = update_shopify_prices(updated_variants)
            stats['shopify_synced'] += shopify_success
            
            print(f"✅ Updated {len(updated_variants)} variants")
        else:
            stats['no_change'] += 1
            print("⏭️  No change")
        
        # Mark as processed
        processed_ids.add(card['card_id'])
        save_progress(series, list(processed_ids))
        
        # Progress update every 25 cards
        if i % 25 == 0:
            elapsed = (datetime.now() - start_time).total_seconds()
            avg_per_card = elapsed / i
            remaining_time = (len(remaining_cards) - i) * avg_per_card
            print(f"\n   📊 Progress: {i}/{len(remaining_cards)} | "
                  f"Updated: {stats['total_updated']} | "
                  f"ETA: {remaining_time/3600:.1f}h\n")
    
    # Final summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print("\n" + "=" * 100)
    print("📊 PRICE UPDATE COMPLETE!")
    print("=" * 100)
    print(f"Cards processed:     {stats['total_processed']}")
    print(f"Cards updated:       {stats['total_updated']}")
    print(f"Variants updated:    {stats['variants_updated']}")
    print(f"Shopify synced:      {stats['shopify_synced']}")
    print(f"No change needed:    {stats['no_change']}")
    print(f"Failed:              {stats['failed']}")
    print(f"\n⏱️  Total time: {duration/3600:.1f} hours")
    print("=" * 100)
    
    # Clean up progress file if complete
    if len(processed_ids) >= len(cards):
        progress_file = f"price_update_{series.replace(' ', '_').replace('&', 'and').lower()}_progress.json"
        if os.path.exists(progress_file):
            os.remove(progress_file)
            print("✅ Progress file cleaned up")
    
    # Send email report
    if EMAIL_ENABLED:
        send_email_report(series, stats, start_time, end_time)


if __name__ == "__main__":
    # Get series from command line argument or default to Scarlet & Violet
    series = sys.argv[1] if len(sys.argv) > 1 else "Scarlet & Violet"
    update_prices_for_series(series)
