"""
DUMPLING COLLECTIBLES - Single Inventory Adjustment

Interactively add or remove inventory for a single card.

Use cases:
- Add inventory: Buylist, wholesale, pack opening
- Remove inventory: Sold outside system (eBay), damaged card, theft, etc.

Features:
- Choose add or remove at start
- Search for card
- Select condition
- Enter quantity (positive number)
- Enter reason for adjustment
- Updates database + Shopify
- Full audit trail

Usage:
    python adjust_inventory_single.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import sys
from datetime import datetime
import requests

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"


def print_header():
    """Print script header"""
    print("\n" + "=" * 70)
    print("📦 INVENTORY ADJUSTMENT - Single Card")
    print("=" * 70)
    print("Add or remove inventory for a single card")
    print("=" * 70 + "\n")


def search_cards(query):
    """Search for cards by name"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT id as card_id, name, set_code, set_name, number, variant
        FROM cards
        WHERE LOWER(name) LIKE LOWER(%s)
        ORDER BY name, set_code, number
        LIMIT 20
    """, (f"%{query}%",))
    
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return results


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
            c.name as card_name,
            c.set_code,
            c.number
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
        print(f"❌ Database error: {str(e)}")
        return False


def log_transaction(variant_id, quantity, transaction_type, source, notes):
    """Log inventory transaction"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO inventory_transactions 
            (variant_id, transaction_type, quantity, unit_cost, reference_type, notes, created_at)
            VALUES (%s, %s, %s, NULL, %s, %s, NOW())
            RETURNING id
        """, (variant_id, transaction_type, quantity, source, notes))
        
        transaction_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return transaction_id
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        print(f"❌ Transaction log error: {str(e)}")
        return None


def sync_to_shopify(shopify_variant_id, new_qty):
    """Update Shopify inventory"""
    if not SHOPIFY_ACCESS_TOKEN or not shopify_variant_id:
        return False
    
    try:
        # Get location ID
        location_id = os.getenv('SHOPIFY_LOCATION_ID')
        if not location_id:
            print("⚠️  SHOPIFY_LOCATION_ID not set - skipping Shopify sync")
            return False
        
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
                "location_id": int(location_id),
                "inventory_item_id": int(inventory_item_id),
                "available": new_qty
            },
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"},
            timeout=10
        )
        
        return response.status_code == 200
    except Exception as e:
        print(f"⚠️  Shopify sync failed: {str(e)}")
        return False


def main():
    """Main program"""
    print_header()
    
    # Step 1: Choose action
    print("What would you like to do?\n")
    print("[1] Add inventory (buylist, wholesale, pack opening, etc.)")
    print("[2] Remove inventory (sold outside system, damaged, theft, etc.)")
    print("[3] Exit")
    
    action = input("\nChoice (1-3): ").strip()
    
    if action == '3':
        print("\n👋 Goodbye!")
        return
    
    if action not in ['1', '2']:
        print("\n❌ Invalid choice")
        return
    
    is_adding = (action == '1')
    action_word = "add" if is_adding else "remove"
    transaction_type = "adjustment" if not is_adding else "purchase"
    
    print(f"\n{'📥' if is_adding else '📤'} {action_word.upper()} INVENTORY MODE\n")
    
    # Step 2: Search for card
    search_query = input(f"🔍 Search for card (name): ").strip()
    
    if not search_query:
        print("\n❌ Search query cannot be empty")
        return
    
    results = search_cards(search_query)
    
    if not results:
        print(f"\n❌ No cards found matching '{search_query}'")
        return
    
    # Display results
    print(f"\n📋 Found {len(results)} card(s):\n")
    for i, card in enumerate(results, 1):
        variant_display = f" ({card['variant']})" if card['variant'] else ""
        print(f"[{i}] {card['name']}{variant_display} - {card['set_name']} ({card['set_code']}) #{card['number']}")
    
    # Select card
    choice = input(f"\nSelect card (1-{len(results)}): ").strip()
    
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(results):
            raise ValueError()
        selected_card = results[idx]
    except:
        print("\n❌ Invalid selection")
        return
    
    print(f"\n✅ Selected: {selected_card['name']} ({selected_card['set_code']}-{selected_card['number']})")
    
    # Step 3: Select condition
    print("\n📊 Select condition:\n")
    print("[1] NM (Near Mint)")
    print("[2] LP (Lightly Played)")
    print("[3] MP (Moderately Played)")
    print("[4] HP (Heavily Played)")
    print("[5] DMG (Damaged)")
    
    cond_choice = input("\nChoice (1-5): ").strip()
    
    condition_map = {
        '1': 'NM',
        '2': 'LP',
        '3': 'MP',
        '4': 'HP',
        '5': 'DMG'
    }
    
    if cond_choice not in condition_map:
        print("\n❌ Invalid condition")
        return
    
    condition = condition_map[cond_choice]
    
    # Get variant info
    variant = get_variant_info(selected_card['card_id'], condition)
    
    if not variant:
        print(f"\n❌ Variant not found for {condition} condition")
        print("💡 This card may not have been uploaded to Shopify yet")
        return
    
    # Display current inventory
    print(f"\n📦 Current inventory: {variant['inventory_qty']} units")
    print(f"💰 Current price: ${float(variant['price_cad']):.2f} CAD")
    
    # Step 4: Get quantity
    while True:
        qty_input = input(f"\n{'➕' if is_adding else '➖'} Quantity to {action_word}: ").strip()
        
        try:
            quantity = int(qty_input)
            if quantity <= 0:
                print("❌ Quantity must be positive")
                continue
            
            # Calculate new inventory
            if is_adding:
                new_qty = variant['inventory_qty'] + quantity
            else:
                new_qty = variant['inventory_qty'] - quantity
                
                if new_qty < 0:
                    print(f"❌ Cannot remove {quantity} units - only {variant['inventory_qty']} available")
                    print(f"💡 Maximum you can remove: {variant['inventory_qty']}")
                    continue
            
            break
        except ValueError:
            print("❌ Please enter a valid number")
    
    # Step 5: Get reason
    if is_adding:
        print("\n📝 Source/reason:")
        print("[1] buylist")
        print("[2] wholesale")
        print("[3] opening")
        print("[4] trade")
        print("[5] personal")
        print("[6] other")
        
        source_choice = input("\nChoice (1-6): ").strip()
        source_map = {
            '1': 'buylist',
            '2': 'wholesale',
            '3': 'opening',
            '4': 'trade',
            '5': 'personal',
            '6': 'other'
        }
        source = source_map.get(source_choice, 'other')
    else:
        print("\n📝 Reason for removal:")
        print("[1] sold_ebay")
        print("[2] sold_other")
        print("[3] damaged")
        print("[4] theft")
        print("[5] lost")
        print("[6] returned")
        print("[7] other")
        
        reason_choice = input("\nChoice (1-7): ").strip()
        reason_map = {
            '1': 'sold_ebay',
            '2': 'sold_other',
            '3': 'damaged',
            '4': 'theft',
            '5': 'lost',
            '6': 'returned',
            '7': 'other'
        }
        source = reason_map.get(reason_choice, 'other')
    
    notes = input("Additional notes (optional): ").strip()
    
    # Confirmation
    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"Card: {variant['card_name']} ({variant['set_code']}-{variant['number']})")
    print(f"Condition: {condition}")
    print(f"Action: {action_word.upper()}")
    print(f"Quantity: {quantity}")
    print(f"Current inventory: {variant['inventory_qty']}")
    print(f"New inventory: {new_qty} {'📈' if is_adding else '📉'}")
    print(f"Reason: {source}")
    if notes:
        print(f"Notes: {notes}")
    print("=" * 70)
    
    confirm = input("\n✅ Confirm? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("\n❌ Cancelled")
        return
    
    # Execute adjustment
    print(f"\n⏳ {action_word.title()}ing inventory...")
    
    # Update database
    if not update_inventory(variant['variant_id'], new_qty):
        print("\n❌ Failed to update database")
        return
    
    # Log transaction
    quantity_to_log = quantity if is_adding else -quantity
    transaction_id = log_transaction(
        variant['variant_id'],
        quantity_to_log,
        transaction_type,
        source,
        notes or f"Manual {action_word} - {source}"
    )
    
    # Sync to Shopify
    shopify_success = False
    if variant['shopify_variant_id']:
        print("⏳ Syncing to Shopify...")
        shopify_success = sync_to_shopify(variant['shopify_variant_id'], new_qty)
    
    # Success message
    print("\n" + "=" * 70)
    print(f"🎉 SUCCESS!")
    print("=" * 70)
    print(f"\nInventory {'added' if is_adding else 'removed'}:")
    print(f"• Database: inventory_qty = {new_qty}")
    if variant['shopify_variant_id']:
        if shopify_success:
            print(f"• Shopify: {new_qty} available")
        else:
            print(f"• Shopify: ⚠️  Sync failed (manual update needed)")
    
    if transaction_id:
        print(f"\nTransaction ID: #{transaction_id}")
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
