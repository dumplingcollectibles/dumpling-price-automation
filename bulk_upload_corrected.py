"""
DUMPLING COLLECTIBLES - Bulk Inventory Adjustment (Interactive)

Interactive CSV-based inventory adjustments with progress tracking.

Supports both additions and removals:
- Positive quantity = ADD inventory
- Negative quantity = REMOVE inventory

Features:
- Interactive file selection
- Template generator
- Real-time progress updates
- Validates before processing
- Exports failed rows
- Full audit trail

Usage:
    python adjust_inventory_bulk_interactive.py
"""

import csv
import sys
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from datetime import datetime
import time

# Import our validator module
import csv_validator

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"


def print_header():
    """Print script header"""
    print("\n" + "=" * 70)
    print("📦 BULK INVENTORY ADJUSTMENT - Interactive Mode")
    print("=" * 70)
    print("Add or remove inventory via CSV upload")
    print("Positive qty = ADD | Negative qty = REMOVE")
    print("=" * 70 + "\n")


def generate_template():
    """Generate CSV template file"""
    template_filename = f"inventory_adjustment_template_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(template_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header - WITH unit_cost
        writer.writerow(['card_name', 'set_code', 'card_number', 'condition', 'quantity', 'unit_cost', 'source', 'notes'])
        
        # Example rows - 3 examples now
        writer.writerow(['Charizard', 'base1', '4', 'NM', '3', '50.00', 'buylist', 'ADD 3 units - paid $50 each'])
        writer.writerow(['Pikachu', 'base1', '58', 'LP', '-1', '', 'sold_ebay', 'REMOVE 1 unit - no cost needed'])
        writer.writerow(['Blastoise', 'base1', '2', 'NM', '1', '', 'opening', 'ADD 1 unit - pulled from pack (no cost)'])
    
    return template_filename


def show_template_help():
    """Display template format help"""
    print("\n📋 CSV TEMPLATE FORMAT:")
    print("=" * 70)
    print("\nRequired Columns:")
    print("  • card_name    - Card name (e.g., Charizard)")
    print("  • set_code     - Set code (e.g., base1, swsh1, sv6)")
    print("  • card_number  - Card number (e.g., 4, 123)")
    print("  • condition    - NM, LP, MP, HP, or DMG")
    print("  • quantity     - Number (positive = add, negative = remove)")
    print("  • unit_cost    - Cost per card (optional, see below)")
    print("  • source       - Any text (e.g., buylist, eBay, wholesale)")
    print("  • notes        - Optional notes\n")
    
    print("Quantity Examples:")
    print("  • 5      = ADD 5 units")
    print("  • -2     = REMOVE 2 units")
    print("  • 10     = ADD 10 units")
    print("  • -1     = REMOVE 1 unit\n")
    
    print("Unit Cost:")
    print("  • For ADDITIONS: Enter cost per card (e.g., 50.00)")
    print("    - Optional: Can leave blank if cost unknown (e.g., pack pulls)")
    print("    - Warning will be shown if blank")
    print("    - Cost basis will NOT be updated if blank")
    print("  • For REMOVALS: Leave blank (cost not needed)")
    print("  • Used to calculate weighted average cost basis\n")
    
    print("Source Examples (any text accepted):")
    print("  • buylist, wholesale, opening, trade, personal")
    print("  • sold_ebay, sold_tcgplayer, damaged, theft, lost")
    print("  • adjustment, inventory_correction, found")
    print("  • Or anything else you want!\n")
    
    print("Example CSV:")
    print("-" * 70)
    print("card_name,set_code,card_number,condition,quantity,unit_cost,source,notes")
    print("Charizard,base1,4,NM,3,50.00,buylist,Paid $50 each")
    print("Pikachu,base1,58,LP,-1,,eBay sale,Removal - no cost")
    print("Blastoise,base1,2,NM,1,,pack opening,Pack pull - no cost")
    print("-" * 70 + "\n")


def read_csv_file(filename):
    """Read CSV file and return rows"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = []
            for i, row in enumerate(reader, start=2):
                row['_row_num'] = i
                rows.append(row)
            return rows, None
    except FileNotFoundError:
        return None, f"File not found: {filename}"
    except Exception as e:
        return None, f"Error reading file: {str(e)}"


def get_variant_info(card_id, condition):
    """Get variant details including current inventory"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT 
            v.id as variant_id,
            v.condition,
            v.inventory_qty,
            v.price_cad,
            v.shopify_variant_id,
            v.cost_basis_avg,
            v.total_units_purchased,
            c.name as card_name
        FROM variants v
        INNER JOIN products p ON p.id = v.product_id
        INNER JOIN cards c ON c.id = p.card_id
        WHERE p.card_id = %s AND v.condition = %s
    """, (card_id, condition))
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return result


def update_inventory(variant_id, new_qty):
    """Update variant inventory quantity"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE variants
            SET inventory_qty = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (new_qty, variant_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return False


def update_cost_basis(variant_id, old_qty, units_added, unit_cost, old_cost_basis, old_total_purchased):
    """Update weighted average cost basis when adding inventory"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        # Calculate new weighted average cost
        old_total_cost = (old_cost_basis or 0) * old_qty
        new_total_cost = unit_cost * units_added
        combined_total_cost = old_total_cost + new_total_cost
        new_qty = old_qty + units_added
        
        new_avg_cost = combined_total_cost / new_qty if new_qty > 0 else 0
        new_total_purchased = (old_total_purchased or 0) + units_added
        
        cursor.execute("""
            UPDATE variants
            SET cost_basis_avg = %s,
                total_units_purchased = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (new_avg_cost, new_total_purchased, variant_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return False


def log_transaction(variant_id, quantity, unit_cost, source, notes):
    """Log inventory transaction"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Determine transaction type based on quantity
    if quantity > 0:
        transaction_type = 'purchase' if source in ['buylist', 'wholesale'] else 'adjustment'
    else:
        transaction_type = 'adjustment'
    
    try:
        cursor.execute("""
            INSERT INTO inventory_transactions 
            (variant_id, transaction_type, quantity, unit_cost, reference_type, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (variant_id, transaction_type, quantity, unit_cost, source, notes))
        
        transaction_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return transaction_id
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return None


def sync_to_shopify(shopify_variant_id, new_qty):
    """Update Shopify inventory"""
    if not SHOPIFY_ACCESS_TOKEN or not shopify_variant_id or not SHOPIFY_LOCATION_ID:
        return False
    
    try:
        # Get inventory item ID
        url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{shopify_variant_id}.json"
        response = requests.get(
            url,
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN},
            timeout=10
        )
        
        if response.status_code != 200:
            return False
        
        inventory_item_id = response.json()['variant']['inventory_item_id']
        
        # Update inventory level
        url = f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels/set.json"
        response = requests.post(
            url,
            json={
                "location_id": int(SHOPIFY_LOCATION_ID),
                "inventory_item_id": int(inventory_item_id),
                "available": new_qty
            },
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"},
            timeout=10
        )
        
        return response.status_code == 200
    except:
        return False


def print_progress_bar(current, total, prefix='', suffix='', length=50):
    """Print a progress bar"""
    percent = int(100 * (current / float(total)))
    filled = int(length * current // total)
    bar = '█' * filled + '-' * (length - filled)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end='', flush=True)
    if current == total:
        print()


def main():
    """Main program"""
    print_header()
    
    # Step 1: Template or Upload?
    print("What would you like to do?\n")
    print("[1] Generate CSV template (download format example)")
    print("[2] Upload CSV file for processing")
    print("[3] View template format help")
    print("[4] Exit")
    
    choice = input("\nChoice (1-4): ").strip()
    
    if choice == '4':
        print("\n👋 Goodbye!")
        return
    
    if choice == '3':
        show_template_help()
        print("\n✅ Press Enter to continue...")
        input()
        return main()  # Return to menu
    
    if choice == '1':
        print("\n📄 Generating template...")
        template_file = generate_template()
        print(f"\n✅ Template created: {template_file}")
        print(f"\n📥 Download the template here:")
        print(f"   {os.path.abspath(template_file)}")
        print("\n📋 This template includes:")
        print("  • Column headers")
        print("  • 3 example rows:")
        print("    - 1 addition WITH cost (buylist)")
        print("    - 1 removal (no cost needed)")
        print("    - 1 addition WITHOUT cost (pack pull)")
        print("\n💡 Steps:")
        print("  1. Open the file in Excel or Google Sheets")
        print("  2. Delete the 3 example rows")
        print("  3. Add your actual inventory adjustments")
        print("  4. Save the file")
        print("  5. Run this script again and choose option [2] to upload!")
        print("\n✅ Press Enter to continue...")
        input()
        return main()  # Return to menu
    
    if choice != '2':
        print("\n❌ Invalid choice")
        return
    
    # Step 2: Get filename
    print("\n📂 Enter CSV filename to upload:")
    print("   (e.g., adjustments.csv or inventory_adjustment_template_20251128.csv)")
    
    filename = input("\nFilename: ").strip()
    
    if not filename:
        print("\n❌ Filename cannot be empty")
        return
    
    # Check if file exists
    if not os.path.exists(filename):
        print(f"\n❌ File not found: {filename}")
        print(f"\n💡 Make sure the file is in the current directory:")
        print(f"   {os.getcwd()}")
        return
    
    # Check database connection
    print("\n🔌 Testing database connection...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        print("✅ Connected!")
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        return
    
    # Read CSV
    print(f"\n📂 Reading file: {filename}")
    rows, error = read_csv_file(filename)
    
    if error:
        print(f"❌ {error}")
        return
    
    print(f"✅ Found: {len(rows)} rows")
    
    # Validate all rows
    print("\n🔍 Validating data...")
    print_progress_bar(0, len(rows), prefix='Progress:', suffix='Complete')
    
    conn = psycopg2.connect(DATABASE_URL)
    
    valid_rows = []
    warning_rows = []
    error_rows = []
    
    for idx, row in enumerate(rows, 1):
        row_num = row['_row_num']
        
        # Custom validation for quantity (allow negative)
        original_qty = row.get('quantity', '').strip()
        
        # Check if quantity is empty or invalid
        if not original_qty:
            error_rows.append({
                'row_num': row_num,
                'errors': ['Quantity cannot be empty'],
                'original_row': row
            })
            print_progress_bar(idx, len(rows), prefix='Progress:', suffix='Complete')
            continue
        
        try:
            qty_value = int(original_qty)
            row['quantity'] = str(abs(qty_value))  # Validator expects positive
        except ValueError:
            error_rows.append({
                'row_num': row_num,
                'errors': [f'Invalid quantity: "{original_qty}" - must be a number'],
                'original_row': row
            })
            print_progress_bar(idx, len(rows), prefix='Progress:', suffix='Complete')
            continue
        
        # Add empty unit_cost if missing (to prevent validator errors)
        if 'unit_cost' not in row or not row.get('unit_cost', '').strip():
            row['unit_cost'] = '0'  # Placeholder for validator
        
        is_valid, warnings, errors, corrections = csv_validator.validate_row(row, row_num, conn)
        
        # Override: Allow any source value (don't validate against predefined list)
        if 'source' in row and row['source'].strip():
            corrections['source'] = row['source'].strip()
        elif 'source' not in corrections or not corrections['source']:
            corrections['source'] = 'adjustment'  # Default if empty
        
        # Remove source-related and unit_cost-related errors since we accept any value
        # This includes "missing unit_cost" and "must be greater than 0"
        errors = [e for e in errors if 'source' not in e.lower() and 'unit' not in e.lower() and 'cost' not in e.lower()]
        warnings = [w for w in warnings if 'source' not in w.lower() and 'unit' not in w.lower() and 'cost' not in w.lower()]
        
        # If only source or unit_cost was invalid, mark as valid now
        if not errors and not is_valid:
            is_valid = True
        
        # Restore original quantity (including negative)
        corrections['quantity'] = qty_value
        corrections['is_removal'] = corrections['quantity'] < 0
        corrections['quantity_abs'] = abs(corrections['quantity'])
        
        # Check for additions without unit_cost (warning, not error)
        if corrections['quantity'] > 0:  # Addition
            unit_cost_value = row.get('unit_cost', '').strip()
            if not unit_cost_value or unit_cost_value == '0':
                warnings.append(
                    f"Adding {corrections['quantity_abs']} unit(s) without unit_cost - "
                    f"cost basis will NOT be updated. Inventory value will increase by current average cost."
                )
        
        if is_valid:
            valid_rows.append({
                'row_num': row_num,
                'data': corrections,
                'warnings': warnings
            })
            if warnings:
                warning_rows.append({
                    'row_num': row_num,
                    'warnings': warnings
                })
        else:
            error_rows.append({
                'row_num': row_num,
                'errors': errors,
                'original_row': row
            })
        
        # Update progress
        print_progress_bar(idx, len(rows), prefix='Progress:', suffix='Complete')
    
    conn.close()
    
    # Show results
    print("\n" + "=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"\n✅ Valid: {len(valid_rows)} rows")
    print(f"⚠️  Warnings: {len(warning_rows)} rows")
    print(f"❌ Errors: {len(error_rows)} rows\n")
    
    # Show warnings
    if warning_rows:
        print("⚠️  WARNINGS (will proceed if confirmed):")
        for item in warning_rows[:5]:
            print(f"Row {item['row_num']}:")
            for warning in item['warnings']:
                print(f"  • {warning}")
        if len(warning_rows) > 5:
            print(f"  ... and {len(warning_rows) - 5} more warnings")
        print()
    
    # Show errors
    if error_rows:
        print("❌ ERRORS (will be skipped):")
        for item in error_rows[:5]:
            print(f"Row {item['row_num']}:")
            for error in item['errors']:
                print(f"  • {error}")
        if len(error_rows) > 5:
            print(f"  ... and {len(error_rows) - 5} more errors")
        print()
    
    print("=" * 70)
    print()
    
    # Export errors if any
    if error_rows:
        error_filename = f"errors_{os.path.basename(filename).replace('.csv', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(error_filename, 'w', newline='', encoding='utf-8') as f:
            fieldnames = list(error_rows[0]['original_row'].keys())
            if '_row_num' in fieldnames:
                fieldnames.remove('_row_num')
            fieldnames.append('error_reason')
            
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for item in error_rows:
                row_data = item['original_row'].copy()
                if '_row_num' in row_data:
                    del row_data['_row_num']
                row_data['error_reason'] = ' | '.join(item['errors'])
                writer.writerow(row_data)
        
        print(f"📄 Validation errors exported to: {error_filename}")
        print(f"   📥 Download here: {os.path.abspath(error_filename)}\n")
    
    # No valid rows
    if not valid_rows:
        print("❌ No valid rows to process.")
        print("\n💡 Fix errors in your CSV and try again!")
        return
    
    # Count additions vs removals
    additions = [r for r in valid_rows if not r['data']['is_removal']]
    removals = [r for r in valid_rows if r['data']['is_removal']]
    
    print(f"📊 Summary:")
    print(f"  ➕ Additions: {len(additions)} rows")
    print(f"  ➖ Removals: {len(removals)} rows")
    print(f"  📋 Total valid: {len(valid_rows)} adjustments")
    print(f"  ⚠️  Skipped errors: {len(error_rows)} rows\n")
    
    # Ask to proceed
    print("Ready to process?")
    print(f"[1] YES - Process {len(valid_rows)} adjustments")
    print("[2] NO - Cancel")
    
    choice = input("\nChoice (1-2): ").strip()
    
    if choice != '1':
        print("\n❌ Cancelled")
        return
    
    # Check inventory availability for removals
    if removals:
        print("\n🔍 Checking inventory availability for removals...")
        print_progress_bar(0, len(removals), prefix='Progress:', suffix='Complete')
        
        insufficient_inventory = []
        
        for idx, item in enumerate(removals, 1):
            data = item['data']
            variant = get_variant_info(data['card_id'], data['condition'])
            
            if variant:
                if variant['inventory_qty'] < data['quantity_abs']:
                    insufficient_inventory.append({
                        'row_num': item['row_num'],
                        'card_name': data['original_row']['card_name'],
                        'condition': data['condition'],
                        'requested': data['quantity_abs'],
                        'available': variant['inventory_qty']
                    })
            
            print_progress_bar(idx, len(removals), prefix='Progress:', suffix='Complete')
        
        if insufficient_inventory:
            print(f"\n⚠️  WARNING: {len(insufficient_inventory)} removal(s) exceed available inventory:")
            for item in insufficient_inventory[:5]:
                print(f"  Row {item['row_num']}: {item['card_name']} ({item['condition']}) - Want: {item['requested']}, Have: {item['available']}")
            if len(insufficient_inventory) > 5:
                print(f"  ... and {len(insufficient_inventory) - 5} more")
            
            print("\nThese rows will be SKIPPED.")
            proceed = input("\nContinue with remaining rows? (y/n): ").strip().lower()
            if proceed != 'y':
                print("\n❌ Cancelled")
                return
    
    # Process adjustments
    print(f"\n⏳ Processing {len(valid_rows)} adjustments...")
    print("=" * 70)
    
    success_count = 0
    shopify_sync_count = 0
    failed_rows = []
    transaction_ids = []
    
    additions_count = 0
    removals_count = 0
    units_added = 0
    units_removed = 0
    
    print_progress_bar(0, len(valid_rows), prefix='Overall:', suffix='Complete')
    
    for i, item in enumerate(valid_rows, 1):
        data = item['data']
        row = data['original_row']
        
        # Get variant
        variant = get_variant_info(data['card_id'], data['condition'])
        
        if not variant:
            failed_rows.append({
                'row_num': item['row_num'],
                'data': row,
                'reason': f'Variant not found for condition: {data["condition"]}'
            })
            print_progress_bar(i, len(valid_rows), prefix='Overall:', suffix='Complete')
            continue
        
        # Calculate new quantity
        old_qty = variant['inventory_qty']
        change = data['quantity']  # Can be positive or negative
        new_qty = old_qty + change
        
        # Check if removal exceeds available
        if new_qty < 0:
            failed_rows.append({
                'row_num': item['row_num'],
                'data': row,
                'reason': f'Insufficient inventory: requested {abs(change)}, available {old_qty}'
            })
            print_progress_bar(i, len(valid_rows), prefix='Overall:', suffix='Complete')
            continue
        
        # Update database
        if update_inventory(variant['variant_id'], new_qty):
            # Get unit_cost from row (for additions)
            unit_cost = None
            if change > 0:  # Only for additions
                unit_cost_str = row.get('unit_cost', '').strip()
                if unit_cost_str:
                    try:
                        unit_cost = float(unit_cost_str)
                        # Update cost basis
                        update_cost_basis(
                            variant['variant_id'],
                            old_qty,
                            change,
                            unit_cost,
                            variant.get('cost_basis_avg'),
                            variant.get('total_units_purchased')
                        )
                    except ValueError:
                        pass  # Invalid cost, skip cost basis update
            
            # Log transaction
            notes = row.get('notes', '') or f"Bulk adjustment - Source: {data['source']}"
            transaction_id = log_transaction(
                variant['variant_id'],
                change,
                unit_cost,  # Pass unit_cost (None for removals)
                data['source'],
                notes
            )
            
            if transaction_id:
                transaction_ids.append(transaction_id)
            
            # Sync to Shopify
            if variant['shopify_variant_id']:
                if sync_to_shopify(variant['shopify_variant_id'], new_qty):
                    shopify_sync_count += 1
            
            success_count += 1
            
            # Track stats
            if change > 0:
                additions_count += 1
                units_added += change
            else:
                removals_count += 1
                units_removed += abs(change)
        else:
            failed_rows.append({
                'row_num': item['row_num'],
                'data': row,
                'reason': 'Database update failed'
            })
        
        print_progress_bar(i, len(valid_rows), prefix='Overall:', suffix='Complete')
        time.sleep(0.05)  # Small delay for visual effect
    
    # Summary
    print("\n" + "=" * 70)
    print("🎉 PROCESSING COMPLETE!")
    print("=" * 70)
    print(f"\nResults:")
    print(f"✅ Successfully processed: {success_count} adjustments")
    print(f"   ➕ Additions: {additions_count} rows ({units_added} units added)")
    print(f"   ➖ Removals: {removals_count} rows ({units_removed} units removed)")
    print(f"   🔄 Shopify synced: {shopify_sync_count}")
    
    if failed_rows:
        print(f"\n❌ Failed: {len(failed_rows)} rows")
    
    if transaction_ids:
        print(f"\n📝 Transaction IDs: #{transaction_ids[0]}-#{transaction_ids[-1]}")
    
    # Export failed rows
    if failed_rows:
        failed_filename = f"failed_{os.path.basename(filename).replace('.csv', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(failed_filename, 'w', newline='', encoding='utf-8') as f:
            fieldnames = list(failed_rows[0]['data'].keys()) + ['failure_reason']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for item in failed_rows:
                row_data = item['data'].copy()
                row_data['failure_reason'] = item['reason']
                writer.writerow(row_data)
        
        print(f"\n📄 Failed rows exported to: {failed_filename}")
        print(f"   📥 Download here: {os.path.abspath(failed_filename)}")
        print(f"   💡 Fix issues and re-upload this file")
    
    if error_rows:
        print(f"\n📄 Validation errors also saved (see above)")
    
    print("\n" + "=" * 70)
    print("\n✅ All done! Check Shopify to verify inventory updates.")
    print()


if __name__ == "__main__":
    main()
