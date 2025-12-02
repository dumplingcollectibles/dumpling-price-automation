"""
Inventory Sync Script - Database → Shopify

Syncs inventory quantities from Neon database to Shopify.

Use this when:
- Weekly audit report shows discrepancies
- After adding inventory via scripts
- After price updates
- After manual adjustments
- When things get out of sync

Simple and safe - just updates Shopify to match your database.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import os
from dotenv import load_dotenv
import time
from datetime import datetime

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
SHOPIFY_RATE_LIMIT = 2  # requests per second
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
    print("📂 Connecting to database...")
    
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


def update_shopify_inventory(inventory_item_id, quantity):
    """Update inventory level in Shopify"""
    rate_limit()
    
    url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels/set.json"
    headers = {
        'X-Shopify-Access-Token': SHOPIFY_ACCESS_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        'location_id': int(SHOPIFY_LOCATION_ID),
        'inventory_item_id': inventory_item_id,
        'available': int(quantity)
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return False


def sync_inventory(dry_run=False, show_all=False):
    """
    Sync inventory from database to Shopify
    
    Args:
        dry_run: If True, only shows what would change without making updates
        show_all: If True, shows all variants including those already in sync
    """
    print("=" * 70)
    print("🔄 INVENTORY SYNC - Database → Shopify")
    print("=" * 70)
    print()
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()
    
    # Get all variants from database
    variants = get_variants_from_database()
    
    if not variants:
        print("❌ No variants found in database with Shopify IDs")
        return
    
    print(f"✅ Found {len(variants)} variants in database\n")
    
    # Track stats
    in_sync_count = 0
    needs_update_count = 0
    updated_count = 0
    error_count = 0
    
    changes = []
    errors = []
    
    print("📊 Checking inventory levels...\n")
    
    for i, variant in enumerate(variants, 1):
        # Progress indicator
        if i % 50 == 0:
            print(f"   Progress: {i}/{len(variants)} variants checked...")
        
        card_name = variant['card_name']
        condition = variant['condition']
        sku = variant['sku']
        db_qty = variant['inventory_qty']
        shopify_variant_id = variant['shopify_variant_id']
        
        # Get inventory_item_id from Shopify
        inventory_item_id = get_inventory_item_id(shopify_variant_id)
        
        if not inventory_item_id:
            errors.append({
                'card': f"{card_name} ({condition})",
                'reason': 'Could not get inventory_item_id'
            })
            error_count += 1
            continue
        
        # Get current Shopify inventory
        shopify_qty = get_shopify_inventory(inventory_item_id)
        
        if shopify_qty is None:
            errors.append({
                'card': f"{card_name} ({condition})",
                'reason': 'Could not get Shopify inventory'
            })
            error_count += 1
            continue
        
        # Compare
        if db_qty == shopify_qty:
            in_sync_count += 1
            if show_all:
                print(f"✅ {card_name} ({condition}): {db_qty} ← Already in sync")
        else:
            needs_update_count += 1
            changes.append({
                'card': f"{card_name} ({condition})",
                'sku': sku,
                'db_qty': db_qty,
                'shopify_qty': shopify_qty,
                'inventory_item_id': inventory_item_id
            })
    
    # Show results
    print()
    print("=" * 70)
    print("SYNC RESULTS")
    print("=" * 70)
    print()
    print(f"✅ In sync: {in_sync_count} variants")
    print(f"⚠️  Needs update: {needs_update_count} variants")
    if error_count > 0:
        print(f"❌ Errors: {error_count} variants")
    print()
    
    # Show changes
    if changes:
        print("=" * 70)
        print("CHANGES NEEDED")
        print("=" * 70)
        print()
        
        for change in changes[:20]:  # Show first 20
            print(f"🔄 {change['card']}")
            print(f"   SKU: {change['sku']}")
            print(f"   Database: {change['db_qty']} | Shopify: {change['shopify_qty']}")
            print(f"   Change: {change['shopify_qty']} → {change['db_qty']}")
            print()
        
        if len(changes) > 20:
            print(f"   ... and {len(changes) - 20} more changes\n")
        
        # Ask for confirmation if not dry run
        if not dry_run:
            print("=" * 70)
            print()
            print("⚠️  IMPORTANT: This will update Shopify to match your database.")
            print("   Make sure database quantities are correct!")
            print()
            choice = input("🔄 Apply these changes to Shopify? (yes/no): ").strip().lower()
            
            if choice != 'yes':
                print("\n❌ Sync cancelled. No changes made.")
                return
            
            print("\n⏳ Updating Shopify inventory...\n")
            
            # Apply changes
            for i, change in enumerate(changes, 1):
                card = change['card']
                new_qty = change['db_qty']
                inventory_item_id = change['inventory_item_id']
                
                if i % 10 == 0:
                    print(f"   Progress: {i}/{len(changes)} updates...")
                
                success = update_shopify_inventory(inventory_item_id, new_qty)
                
                if success:
                    updated_count += 1
                else:
                    error_count += 1
                    errors.append({
                        'card': card,
                        'reason': 'Failed to update Shopify'
                    })
            
            print()
            print("=" * 70)
            print("UPDATE COMPLETE")
            print("=" * 70)
            print()
            print(f"✅ Successfully updated: {updated_count} variants")
            if error_count > 0:
                print(f"❌ Failed: {error_count} variants")
            print()
            
            print("✅ All done! Check Shopify to verify inventory updates.")
            print()
    else:
        print("✅ All inventory levels are in sync! Nothing to update.\n")
    
    # Show errors
    if errors:
        print("=" * 70)
        print("ERRORS")
        print("=" * 70)
        print()
        for error in errors[:10]:
            print(f"❌ {error['card']}: {error['reason']}")
        if len(errors) > 10:
            print(f"   ... and {len(errors) - 10} more errors")
        print()


def main():
    """Main function with menu"""
    print()
    print("=" * 70)
    print("🔄 INVENTORY SYNC SCRIPT")
    print("=" * 70)
    print()
    print("This script syncs inventory from your database to Shopify.")
    print()
    print("⚠️  WARNING: This makes Shopify match your database.")
    print("   Make sure your database is correct before syncing!")
    print()
    print("Options:")
    print("  [1] Dry run - Check what would change (no updates)")
    print("  [2] Sync inventory - Update Shopify to match database")
    print("  [3] Full report - Show all variants including those in sync")
    print("  [4] Exit")
    print()
    
    choice = input("Choice (1-4): ").strip()
    print()
    
    if choice == '1':
        sync_inventory(dry_run=True, show_all=False)
    elif choice == '2':
        sync_inventory(dry_run=False, show_all=False)
    elif choice == '3':
        sync_inventory(dry_run=True, show_all=True)
    elif choice == '4':
        print("👋 Goodbye!")
        return
    else:
        print("❌ Invalid choice")
        return


if __name__ == "__main__":
    main()
