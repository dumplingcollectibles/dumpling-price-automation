"""
DUMPLING COLLECTIBLES - Single Inventory Adjustment Job
Interactively add or remove inventory for a single card.
Refactored to 3-tier Service pattern.

Usage:
    python -m src.inventory.adjust_inventory_single
"""
import sys
import os
import logging
from src.inventory.inventory_service import InventoryService
from src.inventory.inventory_config import inventory_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize domain service
service = InventoryService()

def print_header():
    print("\n" + "=" * 70)
    print("📦 INVENTORY ADJUSTMENT - Single Card")
    print("=" * 70)

def main():
    print_header()
    
    # 1. Action Choice
    print("What would you like to do?\n")
    print("[1] Add inventory (buylist, wholesale, opening, etc.)")
    print("[2] Remove inventory (sold, damaged, theft, etc.)")
    print("[3] Exit")
    
    action = input("\nChoice (1-3): ").strip()
    if action == '3': return
    if action not in ['1', '2']: return

    is_adding = (action == '1')
    mode_text = "ADD" if is_adding else "REMOVE"
    print(f"\n{'📥' if is_adding else '📤'} {mode_text} INVENTORY MODE\n")
    
    # 2. Search
    query = input(f"🔍 Search for card (name): ").strip()
    if not query: return
    
    results = service.search_cards(query)
    if not results:
        print(f"❌ No cards found for '{query}'")
        return
    
    print(f"\n📋 Found {len(results)} card(s):\n")
    for i, c in enumerate(results, 1):
        v_suffix = f" ({c['variant']})" if c['variant'] else ""
        print(f"[{i}] {c['name']}{v_suffix} - {c['set_name']} ({c['set_code']}) #{c['number']}")
    
    choice = input(f"\nSelect card (1-{len(results)}): ").strip()
    try:
        selected = results[int(choice) - 1]
    except: return

    # 3. Condition Select
    print("\n📊 Select condition:")
    for i, cond in enumerate(inventory_config.VALID_CONDITIONS, 1):
        print(f"[{i}] {cond}")
    
    cond_idx = input("\nChoice: ").strip()
    try:
        condition = inventory_config.VALID_CONDITIONS[int(cond_idx) - 1]
    except: return

    # 4. Context & Qty
    variant = service.get_variant_info(selected['card_id'], condition)
    if not variant:
        print(f"❌ Variant not found for {condition}. Must create product first.")
        return
    
    print(f"\n📦 Current: {variant['inventory_qty']} units (Price: ${float(variant['price_cad']):.2f} CAD)")
    
    qty_input = input(f"\n{'➕' if is_adding else '➖'} Quantity to {mode_text.lower()}: ").strip()
    try:
        qty = int(qty_input)
        if qty <= 0: return
        # Logic check for removal
        if not is_adding and variant['inventory_qty'] < qty:
            print(f"❌ Cannot remove {qty} units - only {variant['inventory_qty']} available.")
            return
    except: return

    # 5. Reason/Source
    options = inventory_config.VALID_SOURCES_ADD if is_adding else inventory_config.VALID_REASONS_REMOVE
    print("\n📝 Reason/Source:")
    for i, opt in enumerate(options, 1):
        print(f"[{i}] {opt}")
    
    src_idx = input("\nChoice: ").strip()
    try:
        source = options[int(src_idx) - 1]
    except: source = 'other'
    
    notes = input("Additional notes (optional): ").strip()

    # 6. Execute
    delta = qty if is_adding else -qty
    txn_type = 'purchase' if is_adding else 'adjustment'
    
    # Optional: Get unit cost for additions to recalculate WAC
    unit_cost = None
    if is_adding:
        cost_input = input("Unit Cost (CAD) - Enter to stay as is: ").strip()
        if cost_input: unit_cost = float(cost_input)

    confirm = input(f"\n✅ Confirm {mode_text.lower()}ing {qty} units? (y/n): ").strip().lower()
    if confirm != 'y': return

    print(f"\n⏳ Syncing database and Shopify...")
    success = service.update_quantity(
        variant_id=variant['id'], delta=delta, unit_cost=unit_cost, 
        source=source, notes=notes, transaction_type=txn_type
    )
    
    if success:
        print(f"\n🎉 SUCCESS! Inventory updated to {variant['inventory_qty'] + delta}")
    else:
        print(f"\n❌ Error processing inventory adjustment.")

if __name__ == "__main__":
    main()
