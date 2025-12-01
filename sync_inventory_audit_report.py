"""
Inventory Sync Audit Report - Automated Version

This version is designed to run in GitHub Actions and generate a report.
No interactive prompts - just generates a summary report.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import os
from dotenv import load_dotenv
import time
from datetime import datetime
import sys

load_dotenv()

# Database Config
DATABASE_URL = os.getenv('NEON_DB_URL')

# Shopify Config
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"

# Rate limiting
SHOPIFY_RATE_LIMIT = 2
last_request_time = 0


def rate_limit():
    """Ensure we don't exceed Shopify rate limits"""
    global last_request_time
    current_time = time.time()
    time_since_last = current_time - last_request_time
    
    if time_since_last < (1.0 / SHOPIFY_RATE_LIMIT):
        time.sleep((1.0 / SHOPIFY_RATE_LIMIT) - time_since_last)
    
    last_request_time = time.time()


def get_variants_from_database():
    """Get all variants with Shopify variant IDs from database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT 
            v.id as variant_id,
            v.shopify_variant_id,
            v.inventory_qty,
            v.condition,
            v.sku,
            c.name as card_name,
            c.set_code,
            c.number as card_number
        FROM variants v
        INNER JOIN products p ON p.id = v.product_id
        INNER JOIN cards c ON c.id = p.card_id
        WHERE v.shopify_variant_id IS NOT NULL
        ORDER BY c.name, v.condition
    """)
    
    variants = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return variants


def get_inventory_item_id(shopify_variant_id):
    """Get inventory_item_id from Shopify variant"""
    rate_limit()
    
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{shopify_variant_id}.json"
    headers = {'X-Shopify-Access-Token': SHOPIFY_ACCESS_TOKEN}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            variant = response.json().get('variant', {})
            return variant.get('inventory_item_id')
        return None
    except Exception as e:
        return None


def get_shopify_inventory(inventory_item_id):
    """Get current inventory level from Shopify"""
    rate_limit()
    
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels.json"
    params = {
        'inventory_item_ids': inventory_item_id,
        'location_ids': SHOPIFY_LOCATION_ID
    }
    headers = {'X-Shopify-Access-Token': SHOPIFY_ACCESS_TOKEN}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('inventory_levels'):
                return data['inventory_levels'][0]['available']
        return None
    except Exception as e:
        return None


def generate_audit_report():
    """Generate automated audit report"""
    
    print("=" * 80)
    print("WEEKLY INVENTORY SYNC AUDIT REPORT")
    print("=" * 80)
    print(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get variants from database
    print("📂 Connecting to database...")
    try:
        variants = get_variants_from_database()
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        sys.exit(1)
    
    if not variants:
        print("⚠️  No variants found with Shopify IDs")
        print("\nThis is normal if:")
        print("  - No products uploaded to Shopify yet")
        print("  - All variants missing shopify_variant_id")
        sys.exit(0)
    
    print(f"✅ Found {len(variants)} variants in database\n")
    
    # Track stats
    in_sync_count = 0
    needs_update_count = 0
    error_count = 0
    
    changes = []
    errors = []
    
    print("📊 Checking inventory levels...")
    print()
    
    # Check each variant
    for i, variant in enumerate(variants, 1):
        # Progress indicator every 50 variants
        if i % 50 == 0:
            print(f"   Progress: {i}/{len(variants)} variants checked...")
        
        card_name = variant['card_name']
        condition = variant['condition']
        sku = variant['sku']
        db_qty = variant['inventory_qty']
        shopify_variant_id = variant['shopify_variant_id']
        
        # Get inventory_item_id
        inventory_item_id = get_inventory_item_id(shopify_variant_id)
        
        if not inventory_item_id:
            errors.append({
                'card': f"{card_name} ({condition})",
                'sku': sku,
                'reason': 'Could not get inventory_item_id from Shopify'
            })
            error_count += 1
            continue
        
        # Get Shopify inventory
        shopify_qty = get_shopify_inventory(inventory_item_id)
        
        if shopify_qty is None:
            errors.append({
                'card': f"{card_name} ({condition})",
                'sku': sku,
                'reason': 'Could not get inventory from Shopify API'
            })
            error_count += 1
            continue
        
        # Compare
        if db_qty == shopify_qty:
            in_sync_count += 1
        else:
            needs_update_count += 1
            changes.append({
                'card': f"{card_name} ({condition})",
                'sku': sku,
                'db_qty': db_qty,
                'shopify_qty': shopify_qty,
                'difference': db_qty - shopify_qty
            })
    
    # Generate summary
    print()
    print("=" * 80)
    print("AUDIT SUMMARY")
    print("=" * 80)
    print()
    print(f"Total variants checked: {len(variants)}")
    print(f"✅ In sync: {in_sync_count} variants ({in_sync_count/len(variants)*100:.1f}%)")
    print(f"⚠️  Need update: {needs_update_count} variants ({needs_update_count/len(variants)*100:.1f}%)")
    
    if error_count > 0:
        print(f"❌ Errors: {error_count} variants ({error_count/len(variants)*100:.1f}%)")
    
    print()
    
    # Overall status
    if needs_update_count == 0 and error_count == 0:
        print("🎉 STATUS: EXCELLENT - All inventory is in perfect sync!")
    elif needs_update_count > 0 and needs_update_count < 10:
        print("✅ STATUS: GOOD - Minor discrepancies found (less than 10)")
    elif needs_update_count >= 10 and needs_update_count < 50:
        print("⚠️  STATUS: ATTENTION NEEDED - Multiple discrepancies found")
    else:
        print("🚨 STATUS: ACTION REQUIRED - Significant sync issues detected")
    
    print()
    
    # Show changes that need attention
    if changes:
        print("=" * 80)
        print("VARIANTS NEEDING ATTENTION")
        print("=" * 80)
        print()
        
        # Sort by absolute difference (biggest issues first)
        changes.sort(key=lambda x: abs(x['difference']), reverse=True)
        
        # Show top 20
        for i, change in enumerate(changes[:20], 1):
            print(f"{i}. {change['card']}")
            print(f"   SKU: {change['sku']}")
            print(f"   Database: {change['db_qty']} | Shopify: {change['shopify_qty']}")
            print(f"   Difference: {change['difference']:+d} ({'+' if change['difference'] > 0 else ''}will update Shopify to {change['db_qty']})")
            print()
        
        if len(changes) > 20:
            print(f"... and {len(changes) - 20} more variants need updates")
            print()
        
        print("=" * 80)
        print("RECOMMENDED ACTION")
        print("=" * 80)
        print()
        print("To fix these discrepancies, run:")
        print("  python sync_inventory_to_shopify.py")
        print()
        print("Then choose option [2] to sync inventory.")
        print()
    
    # Show errors
    if errors:
        print("=" * 80)
        print("ERRORS ENCOUNTERED")
        print("=" * 80)
        print()
        
        for i, error in enumerate(errors[:10], 1):
            print(f"{i}. {error['card']}")
            print(f"   SKU: {error['sku']}")
            print(f"   Error: {error['reason']}")
            print()
        
        if len(errors) > 10:
            print(f"... and {len(errors) - 10} more errors")
            print()
        
        print("These errors might indicate:")
        print("  - Products deleted in Shopify but not in database")
        print("  - Shopify API rate limiting")
        print("  - Network connectivity issues")
        print()
    
    # Final recommendations
    print("=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print()
    
    if needs_update_count == 0 and error_count == 0:
        print("✅ No action needed - everything is in sync!")
        print("   Continue regular operations.")
    elif needs_update_count > 0 and needs_update_count < 10:
        print("✅ Minor sync recommended:")
        print("   Run: python sync_inventory_to_shopify.py")
        print("   This will fix the few discrepancies found.")
    elif needs_update_count >= 10:
        print("⚠️  Sync recommended:")
        print("   Run: python sync_inventory_to_shopify.py")
        print("   Review changes carefully before confirming.")
    
    if error_count > 0:
        print("\n⚠️  Errors found:")
        print("   Review error list above")
        print("   Check Shopify products are still active")
        print("   Verify database shopify_variant_ids are correct")
    
    print()
    print("=" * 80)
    print("END OF REPORT")
    print("=" * 80)
    
    # Exit with appropriate code
    if error_count > 10:
        sys.exit(1)  # Too many errors
    else:
        sys.exit(0)  # Success


if __name__ == "__main__":
    try:
        generate_audit_report()
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}")
        print("\nPlease check:")
        print("  - Database connection (NEON_DB_URL)")
        print("  - Shopify credentials (SHOPIFY_ACCESS_TOKEN)")
        print("  - Network connectivity")
        sys.exit(1)
