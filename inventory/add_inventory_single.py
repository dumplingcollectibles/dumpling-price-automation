"""
DUMPLING COLLECTIBLES - Add Inventory (Single Card Entry)

Interactive script to add individual cards to inventory.
Features:
- Search cards by name
- Select condition
- Enter quantity, cost, source
- Auto-calculate weighted average cost
- Update database
- Sync to Shopify
- Show profit potential

Usage:
    python add_inventory_single.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import requests
from datetime import datetime

load_dotenv()

# Configuration
DATABASE_URL = os.getenv('NEON_DB_URL')
SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')

if SHOPIFY_SHOP_URL and not SHOPIFY_SHOP_URL.startswith('https://'):
    SHOPIFY_SHOP_URL = f"https://{SHOPIFY_SHOP_URL}"

# Valid sources
VALID_SOURCES = {
    '1': 'buylist',
    '2': 'wholesale',
    '3': 'opening',
    '4': 'personal',
    '5': 'trade',
    '6': 'other'
}

CONDITIONS = {
    '1': 'NM',
    '2': 'LP',
    '3': 'MP',
    '4': 'HP',
    '5': 'DMG'
}


def print_header():
    """Print script header"""
    print("\n" + "=" * 70)
    print("🏪  DUMPLING COLLECTIBLES - Add Inventory")
    print("=" * 70)
    print()


def search_cards(search_term):
    """Search for cards by name"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Search for cards matching the term
        cursor.execute("""
            SELECT 
                c.id,
                c.name,
                c.set_code,
                c.set_name,
                c.number,
                c.img_url
            FROM cards c
            WHERE c.name ILIKE %s
            ORDER BY c.name, c.set_name
            LIMIT 20
        """, (f'%{search_term}%',))
        
        results = cursor.fetchall()
        return results
        
    finally:
        cursor.close()
        conn.close()


def get_variant_info(card_id, condition):
    """Get variant information for a specific card and condition"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                v.id as variant_id,
                v.condition,
                v.sku,
                v.inventory_qty,
                v.price_cad,
                v.cost_basis_avg,
                v.total_units_purchased,
                v.shopify_variant_id,
                p.id as product_id,
                p.shopify_product_id
            FROM variants v
            JOIN products p ON p.id = v.product_id
            WHERE p.card_id = %s
            AND v.condition = %s
        """, (card_id, condition))
        
        variant = cursor.fetchone()
        return variant
        
    finally:
        cursor.close()
        conn.close()


def calculate_new_wac(old_qty, old_wac, new_qty, new_cost):
    """Calculate weighted average cost"""
    if old_wac is None or old_qty == 0:
        # First purchase
        return new_cost
    
    # Calculate weighted average
    old_total_value = old_qty * old_wac
    new_total_value = new_qty * new_cost
    combined_value = old_total_value + new_total_value
    combined_qty = old_qty + new_qty
    
    return round(combined_value / combined_qty, 2)


def update_inventory(variant_id, new_qty, new_wac, total_units):
    """Update variant inventory in database"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE variants
            SET 
                inventory_qty = %s,
                cost_basis_avg = %s,
                total_units_purchased = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (new_qty, new_wac, total_units, variant_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Database error: {str(e)}")
        return False
        
    finally:
        cursor.close()
        conn.close()


def log_transaction(variant_id, quantity, unit_cost, source, notes, reference_type='manual', reference_id=None):
    """Log inventory transaction"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO inventory_transactions (
                variant_id,
                transaction_type,
                quantity,
                unit_cost,
                reference_type,
                reference_id,
                notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (variant_id, 'purchase', quantity, unit_cost, reference_type, reference_id, notes))
        
        transaction_id = cursor.fetchone()[0]
        conn.commit()
        return transaction_id
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Transaction log error: {str(e)}")
        return None
        
    finally:
        cursor.close()
        conn.close()


def sync_to_shopify(shopify_variant_id, new_qty):
    """Sync inventory quantity to Shopify"""
    if not SHOPIFY_ACCESS_TOKEN or not SHOPIFY_LOCATION_ID:
        print("\n⚠️  Shopify credentials missing, skipping sync")
        return False
    
    if not shopify_variant_id:
        print("\n⚠️  No Shopify variant ID, skipping sync")
        return False
    
    try:
        # Get inventory item ID first
        response = requests.get(
            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/variants/{shopify_variant_id}.json",
            headers={"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN},
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"\n⚠️  Failed to get Shopify variant (status {response.status_code})")
            return False
        
        inventory_item_id = response.json()['variant']['inventory_item_id']
        
        # Update inventory level
        response = requests.post(
            f"{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}/inventory_levels/set.json",
            json={
                "location_id": int(SHOPIFY_LOCATION_ID),
                "inventory_item_id": inventory_item_id,
                "available": new_qty
            },
            headers={
                "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            return True
        else:
            print(f"\n⚠️  Shopify sync failed (status {response.status_code})")
            return False
            
    except Exception as e:
        print(f"\n⚠️  Shopify sync error: {str(e)}")
        return False


def add_card_interactive():
    """Main interactive flow to add a card"""
    
    # Step 1: Search for card
    while True:
        search_term = input("\n🔍 Enter card name (or 'q' to quit): ").strip()
        
        if search_term.lower() == 'q':
            return False
        
        if len(search_term) < 2:
            print("❌ Please enter at least 2 characters")
            continue
        
        print(f"\n🔍 Searching for '{search_term}'...")
        
        results = search_cards(search_term)
        
        if not results:
            print(f"\n❌ No cards found matching '{search_term}'")
            retry = input("\nTry another search? (y/n): ").strip().lower()
            if retry != 'y':
                return False
            continue
        
        # Display results
        print(f"\n📋 Found {len(results)} match(es):\n")
        for i, card in enumerate(results, 1):
            print(f"{i}. {card['name']} - {card['set_name']} (#{card['number']})")
            print(f"   Set Code: {card['set_code']}")
        
        # Select card
        while True:
            try:
                choice = input(f"\nSelect card (1-{len(results)}) or 'b' to search again: ").strip()
                
                if choice.lower() == 'b':
                    break
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(results):
                    selected_card = results[choice_num - 1]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(results)}")
            except ValueError:
                print("❌ Please enter a valid number")
        
        if choice.lower() == 'b':
            continue
        
        break
    
    # Step 2: Select condition
    print(f"\n📦 Selected: {selected_card['name']} ({selected_card['set_code']}-{selected_card['number']})")
    print("\nSelect condition:")
    print("1. Near Mint (NM)")
    print("2. Lightly Played (LP)")
    print("3. Moderately Played (MP)")
    print("4. Heavily Played (HP)")
    print("5. Damaged (DMG)")
    
    while True:
        condition_choice = input("\nChoice (1-5): ").strip()
        if condition_choice in CONDITIONS:
            condition = CONDITIONS[condition_choice]
            break
        print("❌ Invalid choice, please enter 1-5")
    
    # Get variant info
    variant = get_variant_info(selected_card['id'], condition)
    
    if not variant:
        print(f"\n❌ Error: Could not find {condition} variant for this card")
        return False
    
    print(f"\n📊 Current inventory: {variant['inventory_qty']} in stock")
    if variant['cost_basis_avg']:
        print(f"   Current cost basis: ${variant['cost_basis_avg']:.2f}")
    print(f"   Selling price: ${variant['price_cad']:.2f}")
    
    # Step 3: Enter quantity
    while True:
        try:
            qty_input = input("\n📦 Quantity to add: ").strip()
            quantity = int(qty_input)
            if quantity > 0:
                break
            print("❌ Quantity must be greater than 0")
        except ValueError:
            print("❌ Please enter a valid number")
    
    # Step 4: Enter cost
    while True:
        try:
            cost_input = input(f"\n💰 Cost per card (CAD): $").strip()
            unit_cost = float(cost_input)
            if unit_cost > 0:
                break
            print("❌ Cost must be greater than 0")
        except ValueError:
            print("❌ Please enter a valid number")
    
    # Step 5: Select source
    print("\n📥 Source:")
    print("1. Buylist (customer)")
    print("2. Wholesale (distributor)")
    print("3. Pack Opening")
    print("4. Personal Collection")
    print("5. Trade")
    print("6. Other")
    
    while True:
        source_choice = input("\nChoice (1-6): ").strip()
        if source_choice in VALID_SOURCES:
            source = VALID_SOURCES[source_choice]
            break
        print("❌ Invalid choice, please enter 1-6")
    
    # Step 6: Notes (optional)
    notes = input("\n📝 Notes (optional, press Enter to skip): ").strip()
    if not notes:
        notes = f"Added via single entry - Source: {source}"
    
    # Calculate new values
    old_qty = variant['inventory_qty']
    old_wac = variant['cost_basis_avg']
    new_qty = old_qty + quantity
    new_wac = calculate_new_wac(old_qty, old_wac, quantity, unit_cost)
    total_units = (variant['total_units_purchased'] or 0) + quantity
    
    # Show summary
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)
    print(f"Card: {selected_card['name']} ({selected_card['set_code']}-{selected_card['number']})")
    print(f"Condition: {condition}")
    print(f"Quantity: +{quantity} ({old_qty} → {new_qty})")
    print(f"Cost: ${unit_cost:.2f} per card")
    print(f"Total: ${unit_cost * quantity:.2f}")
    print(f"Source: {source.title()}")
    if notes:
        print(f"Notes: {notes}")
    print()
    print(f"Cost Basis: ${old_wac:.2f} → ${new_wac:.2f}" if old_wac else f"Cost Basis: ${new_wac:.2f} (new)")
    print(f"Selling Price: ${float(variant['price_cad']):.2f}")
    profit_per = float(variant['price_cad']) - new_wac
    print(f"Potential Profit: ${profit_per:.2f} per card (${profit_per * new_qty:.2f} total)")
    print("=" * 70)
    
    # Confirm
    confirm = input("\n✅ Confirm and save? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("\n❌ Cancelled")
        return False
    
    # Execute updates
    print("\n⏳ Updating inventory...")
    
    # Update database
    if not update_inventory(variant['variant_id'], new_qty, new_wac, total_units):
        return False
    
    print("✅ Database updated")
    
    # Log transaction
    transaction_id = log_transaction(
        variant['variant_id'],
        quantity,
        unit_cost,
        source,
        notes
    )
    
    if transaction_id:
        print(f"✅ Transaction logged (ID: #{transaction_id})")
    
    # Sync to Shopify
    if variant['shopify_variant_id']:
        print("⏳ Syncing to Shopify...")
        if sync_to_shopify(variant['shopify_variant_id'], new_qty):
            print("✅ Shopify synced")
        else:
            print("⚠️  Shopify sync failed (inventory updated in database only)")
    else:
        print("⚠️  No Shopify variant ID (skipping Shopify sync)")
    
    # Success!
    print("\n" + "=" * 70)
    print("🎉 SUCCESS!")
    print("=" * 70)
    print(f"\nInventory updated:")
    print(f"• Database: inventory_qty = {new_qty}")
    print(f"• Cost basis: ${new_wac:.2f}")
    if variant['shopify_variant_id']:
        print(f"• Shopify: {new_qty} available for purchase")
    print()
    
    return True


def main():
    """Main program loop"""
    print_header()
    
    # Check database connection
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
    except Exception as e:
        print(f"❌ Database connection failed: {str(e)}")
        print("\nPlease check your NEON_DB_URL in .env file")
        return
    
    print("Welcome! Let's add some inventory.\n")
    
    while True:
        success = add_card_interactive()
        
        if not success:
            break
        
        # Ask if want to add another
        print("\nNext action:")
        print("1. Add another card")
        print("2. Exit")
        
        choice = input("\nChoice (1-2): ").strip()
        
        if choice != '1':
            break
    
    print("\n" + "=" * 70)
    print("👋 Thanks for using Dumpling Collectibles Inventory Manager!")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()

