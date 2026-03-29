"""
Inventory Sync Script - Database → Shopify
Consolidated 3-tier Pattern.

Usage:
    python -m src.inventory.sync_inventory_to_shopify [--audit]
"""
import sys
import argparse
import logging
from src.inventory.inventory_service import InventoryService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

service = InventoryService()

def main():
    parser = argparse.ArgumentParser(description='Inventory Sync Tool')
    parser.add_argument('--audit', action='store_true', help='Run in non-interactive audit mode')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("🔄 INVENTORY SYNC - Database → Shopify")
    print("=" * 70)
    
    # 1. Fetch data
    variants = service.get_all_linked_variants()
    print(f"✅ Found {len(variants)} variants in database\n")

    print("📊 Checking for discrepancies (this may take a while)...")
    discrepancies = []
    
    for i, v in enumerate(variants, 1):
        if i % 25 == 0:
            print(f"   Progress: {i}/{len(variants)} checked...")
            
        real_qty = service.get_current_shopify_qty(v['shopify_variant_id'])
        if real_qty is not None and real_qty != v['inventory_qty']:
            discrepancies.append({
                'name': v['card_name'],
                'cond': v['condition'],
                'db': v['inventory_qty'],
                'shop': real_qty,
                'id': v['shopify_variant_id']
            })

    if not discrepancies:
        print("\n✅ All variants are already in sync!")
        return

    # 2. Report & Confirm
    print(f"\n⚠️  Found {len(discrepancies)} discrepancies:\n")
    for d in discrepancies[:20]:
        print(f"  • {d['name']} ({d['cond']}): DB={d['db']}, Shopify={d['shop']} → Setting to {d['db']}")
    
    if len(discrepancies) > 20:
        print(f"  ... and {len(discrepancies)-20} more.")

    if args.audit:
        print("\n📝 Audit mode complete. No changes made.")
        return

    confirm = input("\n🔄 Apply these changes to Shopify? (yes/no): ").strip().lower()
    if confirm != 'yes': return

    # 3. Apply
    print(f"\n⏳ Syncing...")
    success_count = 0
    for d in discrepancies:
        if service.sync_to_shopify(d['id'], d['db']):
            success_count += 1
            
    print(f"\n✅ Sync complete! {success_count} variants updated.")

if __name__ == "__main__":
    main()
