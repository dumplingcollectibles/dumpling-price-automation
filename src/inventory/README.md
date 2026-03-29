# 🍱 Inventory Domain

This domain handles the ingestion, auditing, and synchronization of physical Pokémon card stock. It follows a **3-tier service architecture** to ensure data integrity across the database and the Shopify storefront.

## 🏗️ Architecture

1.  **Service Layer (`inventory_service.py`)**: The brain of the domain. Encapsulates Weighted Average Cost (WAC) math, PokemonTCG API fetching, and Shopify product orchestration.
2.  **Config Layer (`inventory_config.py`)**: Centralizes buylist payout matrices, condition multipliers, and market price floors.
3.  **Controller Layer (CLIs)**: Entry points for terminal interactions. These scripts (`inventory_cli_*.py`) handle input parsing and pass all logic execution to the Service.

---

## 🚀 Interactive CLI Tools

### 🛠️ Single Adjust (`inventory_cli_single_adjust.py`)
Used for manual search-and-payout adjustments. Ideal for one-off intake or fixing mistakes.
```bash
python -m src.inventory.inventory_cli_single_adjust
```

### 📦 Bulk Add (`inventory_cli_bulk_add.py`)
Streamlined CSV batch processing for wholesale orders or customer buylists.
```bash
python -m src.inventory.inventory_cli_bulk_add path/to/order.csv
```
*   **Automatic Creation**: If a card is missing, the service fetches API data and publishes the product to Shopify instantly.
*   **Error Safe**: Failed rows are exported to a timestamped CSV for retry.

### 🔄 Shopify Sync (`inventory_cli_shopify_sync.py`)
Resolves drift between the local Postgres ledger and Shopify's inventory levels.
```bash
# Interactive Mode
python -m src.inventory.inventory_cli_shopify_sync

# Audit-Only Mode (No changes)
python -m src.inventory.inventory_cli_shopify_sync --audit
```

---

## 📈 Financial Logic

### **Weighted Average Cost (WAC)**
Inventory value is calculated dynamically when adding stock:
- `(Old Qty * Old WAC) + (New Qty * Unit Cost) / (Old Qty + New Qty) = New WAC`

### **Buylist Matrix**
Payouts are determined by market value (CAD) and condition:
- Under $50: 60% Cash / 70% Credit
- $50 - $100: 70% Cash / 80% Credit
- $100+: 75% Cash / 85% Credit
*(Condition modifiers of 0.75x for LP and 0.50x for MP apply to these bases)*

---

## 📂 Data Format
CSV uploads must include:
`name, set_code, number, condition, quantity, unit_cost`

Template: `sample_inventory_upload.csv`
