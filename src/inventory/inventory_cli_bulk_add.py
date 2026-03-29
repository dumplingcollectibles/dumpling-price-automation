"""
DUMPLING COLLECTIBLES - Bulk Inventory Upload Job
Processes CSV files to bulk-add variants and sync inventory with Shopify.
Refactored to 3-tier Service pattern.

Usage:
    python -m src.inventory.add_inventory_bulk <filename.csv>
"""
import csv
import sys
import os
import logging
from src.inventory.inventory_service import InventoryService

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Initialize domain service
service = InventoryService()

def print_header():
    print("\n" + "=" * 70)
    print("📦 DUMPLING COLLECTIBLES - Bulk Inventory Upload")
    print("=" * 70)

def main():
    print_header()
    
    if len(sys.argv) < 2:
        print("❌ Usage: python -m src.inventory.add_inventory_bulk <filename.csv>")
        return
    
    filename = sys.argv[1]
    if not os.path.exists(filename):
        print(f"❌ File not found: {filename}")
        return

    # 1. Read & Validate
    print(f"📂 Reading: {filename}")
    valid_rows, error_rows = [], []
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            is_valid, warnings, errors, corrections = service.validate_row(row)
            if is_valid:
                valid_rows.append({'row': i, 'data': corrections, 'warnings': warnings})
            else:
                error_rows.append({'row': i, 'errors': errors, 'raw': row})

    print(f"🔍 Validation: {len(valid_rows)} Valid, {len(error_rows)} Errors")
    
    if error_rows:
        print(f"⚠️  Skipping {len(error_rows)} invalid rows (see errors.csv)")
        # Optionally write errors.csv here

    if not valid_rows:
        print("❌ No valid rows to process.")
        return

    # 2. Confirm
    confirm = input(f"\n✅ Ready to process {len(valid_rows)} cards? (y/n): ").strip().lower()
    if confirm != 'y': return

    # 3. Process
    print(f"\n⏳ Processing updates...")
    stats = {'success': 0, 'created': 0, 'failed': 0}
    
    for item in valid_rows:
        data = item['data']
        
        # A. Handle missing cards via API auto-fetch
        if data.get('needs_api_fetch'):
            print(f"  ✨ Fetching API data for {data['original_row']['card_name']}...")
            api_card = service.fetch_card_from_api(data['original_row']['set_code'], data['original_row']['card_number'])
            if api_card:
                m_price = service.extract_market_price(api_card)
                data['card_id'] = service.create_card_record(api_card, m_price)
                stats['created'] += 1
            else:
                print(f"  ❌ API Fetch failed for {data['original_row']['card_name']}")
                stats['failed'] += 1
                continue

        # B. Resolve variant
        variant = service.get_variant_info(data['card_id'], data['condition'])
        if not variant:
            print(f"  ❌ Variant logic error for {data['card_id']}")
            stats['failed'] += 1
            continue

        # C. Update Quantity
        notes = data['original_row'].get('notes', f"Bulk Upload: {filename}")
        success = service.update_quantity(
            variant_id=variant['id'], delta=data['quantity'], 
            unit_cost=data['unit_cost'], source=data['source'],
            notes=notes, transaction_type='purchase'
        )
        
        if success:
            stats['success'] += 1
        else:
            stats['failed'] += 1

    # 4. Final Summary
    print("\n" + "=" * 70)
    print("✅ BATCH COMPLETE")
    print(f"• Successfully updated: {stats['success']}")
    print(f"• New cards created: {stats['created']}")
    print(f"• Total failures: {stats['failed']}")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
