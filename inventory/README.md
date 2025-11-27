# Inventory Management System

Professional inventory management for Dumpling Collectibles with weighted average cost tracking and Shopify sync.

---

## 🎯 Features

- ✅ Single card entry (interactive CLI)
- ✅ Bulk CSV upload (batch processing)
- ✅ Weighted average cost tracking
- ✅ Automatic Shopify sync
- ✅ Complete audit trail
- ✅ Error detection & reporting
- ✅ Failed rows export

---

## 📦 Files

### **Scripts**

- **`add_inventory_single.py`** - Add cards one at a time (interactive)
- **`add_inventory_bulk.py`** - Upload multiple cards from CSV
- **`csv_validator.py`** - Validation helper module
- **`test_inventory_setup.py`** - Pre-flight setup check

### **Templates**

- **`sample_inventory_upload.csv`** - Example CSV format

---

## 🚀 Quick Start

### **1. Install Dependencies**

```bash
pip install psycopg2-binary requests python-dotenv
```

### **2. Configure Environment**

Create `.env` file in project root:

```bash
# Database (Required)
NEON_DB_URL=postgresql://user:pass@host/db?sslmode=require

# Shopify (Required for sync)
SHOPIFY_SHOP_URL=https://your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx
SHOPIFY_LOCATION_ID=123456789
SHOPIFY_API_VERSION=2025-01
```

### **3. Test Setup**

```bash
python inventory/test_inventory_setup.py
```

---

## 📝 Usage

### **Single Card Entry**

```bash
python inventory/add_inventory_single.py
```

**Use for:**
- Pack openings (1-3 cards)
- Quick additions
- Testing

**Time:** 1-2 minutes per card

---

### **Bulk CSV Upload**

```bash
python inventory/add_inventory_bulk.py buylist.csv
```

**Use for:**
- Large buylists (20+ cards)
- Wholesale orders
- Collection buyouts

**Time:** 1-2 seconds per card

---

## 📊 CSV Format

### **Required Columns**

```csv
card_name,set_code,card_number,condition,quantity,unit_cost,source,notes
Charizard VMAX,swsh1,142,NM,2,80.00,buylist,Customer John
Pikachu ex,sv8,245,LP,1,45.00,wholesale,Bulk order
```

| Column | Description | Example |
|--------|-------------|---------|
| `card_name` | Full card name | Charizard VMAX |
| `set_code` | Set identifier | swsh1, sv6 |
| `card_number` | Card # in set | 142 |
| `condition` | NM/LP/MP/HP/DMG | NM |
| `quantity` | How many | 2 |
| `unit_cost` | Cost per card (CAD) | 80.00 |
| `source` | Where from | buylist, wholesale |
| `notes` | Optional notes | Customer name |

### **Valid Conditions**

- `NM` - Near Mint
- `LP` - Lightly Played
- `MP` - Moderately Played
- `HP` - Heavily Played
- `DMG` - Damaged

### **Valid Sources**

- `buylist` - Bought from customer
- `wholesale` - Distributor/supplier
- `opening` - Pulled from packs
- `personal` - Personal collection
- `trade` - Traded
- `gift` - Gift
- `return` - Customer return
- `other` - Other

---

## 🔄 Workflow

### **If Cards Already in Database:**

```bash
# Just add inventory!
python inventory/add_inventory_bulk.py buylist.csv
```

### **If Cards NOT in Database:**

```bash
# 1. Upload inventory (some will fail)
python inventory/add_inventory_bulk.py buylist.csv

# 2. Check failed rows
# Opens: failed_buylist_TIMESTAMP.csv

# 3. Upload missing products
python bulk_upload_corrected.py  # Your product upload script

# 4. Re-run with failed rows (now products exist)
python inventory/add_inventory_bulk.py failed_buylist_TIMESTAMP.csv
```

---

## 📄 Output Files

### **Validation Errors**

**File:** `errors_[filename].csv`

Contains rows with format issues:
- Invalid set codes
- Wrong data types
- Missing required fields

### **Processing Failures**

**File:** `failed_[filename]_[timestamp].csv`

Contains rows that couldn't be processed:
- Cards not in database
- Variant not found
- Database errors

**Both files can be fixed and re-uploaded!**

---

## 💡 Business Logic

### **Weighted Average Cost (WAC)**

```
Current: 2 cards @ $80 = $160
Adding: 3 cards @ $90 = $270
─────────────────────────────
Total: 5 cards for $430
New WAC: $430 ÷ 5 = $86.00
```

**Why WAC?**
- Industry standard
- Accurate profit tracking
- Handles price fluctuations
- Required for accounting

### **Database Updates**

Each inventory addition updates:

1. **`variants` table**
   - `inventory_qty` → New total
   - `cost_basis_avg` → New WAC
   - `total_units_purchased` → Lifetime total

2. **`inventory_transactions` table**
   - Complete audit log
   - Transaction type, quantity, cost
   - Source and notes
   - Timestamp

3. **Shopify (via API)**
   - Inventory level synced
   - Product shows "In Stock"
   - Add to Cart enabled

---

## 🧪 Testing

### **Test Single Entry:**

```bash
python inventory/add_inventory_single.py

# Try these:
1. Add a card (NM condition)
2. Add same card again (different cost) - verify WAC
3. Add same card (LP condition) - verify separate tracking
4. Try invalid quantity (0) - verify error handling
```

### **Test Bulk Upload:**

```bash
# Use sample file
python inventory/add_inventory_bulk.py inventory/sample_inventory_upload.csv

# Check:
- Validation results
- Processing speed
- Failed rows export (if any)
- Shopify inventory updated
```

---

## 📊 Performance

**Single Entry:**
- Time: 1-2 minutes per card
- DB queries: 4 per card
- Shopify calls: 2 per card

**Bulk Upload:**
- Time: 1-2 seconds per card
- 50-card upload: ~2 minutes total
- **95% faster than manual!**

---

## 🔍 Troubleshooting

### **"Database connection failed"**

Check `NEON_DB_URL` in `.env`:
- Must end with `?sslmode=require`
- Verify credentials are correct

### **"Card not in database"**

1. Run product upload first:
   ```bash
   python bulk_upload_corrected.py
   ```
2. Then retry inventory upload

### **"Shopify sync failed"**

Check `.env` has:
- `SHOPIFY_SHOP_URL`
- `SHOPIFY_ACCESS_TOKEN`
- `SHOPIFY_LOCATION_ID`

**Note:** Inventory still saves to database even if Shopify sync fails!

---

## 📈 Time Savings

### **50-Card Buylist Example:**

**Manual (one-by-one):**
- 50 cards × 2 min = 100 minutes

**Bulk Upload:**
- CSV prep: 2 min
- Upload: 2 min
- **Total: 4 minutes**

**Savings: 96 minutes (95% faster!)**

### **Annual Impact:**

- 2 buylists/week × 50 cards = 100 cards/week
- Time saved: 192 min/week
- **Annual: 165 hours saved!**

---

## 🔐 Security

- Database credentials in `.env` (not committed)
- `.env` listed in `.gitignore`
- Parameterized SQL queries (SQL injection prevention)
- API tokens never logged

---

## 📚 Full Documentation

- **ADD_INVENTORY_GUIDE.md** - Complete single entry guide
- **BULK_UPLOAD_GUIDE.md** - Complete bulk upload guide
- **QUICKSTART_INVENTORY.md** - Quick reference
- **INVENTORY_SYSTEM_SUMMARY.md** - System overview

---

## 🎯 Next Features (Roadmap)

**Phase 3: Viewing & Reports**
- [ ] View inventory script
- [ ] Inventory history viewer
- [ ] Profit reports

**Phase 4: Order Integration**
- [ ] Order sync from Shopify
- [ ] Auto-reduce inventory
- [ ] Revenue tracking

**Phase 5: Web Interface**
- [ ] Dashboard
- [ ] Team collaboration
- [ ] Mobile responsive

---

## ✅ System Status

**Production Ready:** ✅

- Single card entry: Tested ✅
- Bulk CSV upload: Tested ✅
- WAC calculation: Verified ✅
- Shopify sync: Working ✅
- Error handling: Complete ✅
- Failed rows export: Working ✅

---

## 🆘 Support

**Common Issues:**
1. Wrong CSV format → Check column names match exactly
2. Cards not in DB → Run product upload first
3. Shopify not syncing → Verify credentials in `.env`

**Need Help?**
- Check documentation files
- Review error messages (they're detailed!)
- Test with `sample_inventory_upload.csv`

---

## 📝 Version History

**v2.1** (Current)
- ✅ Single card entry
- ✅ Bulk CSV upload
- ✅ Complete failed rows export
- ✅ Removed auto-product creation (speed improvement)
- ✅ WAC calculation
- ✅ Shopify sync

---

**Built for:** Dumpling Collectibles  
**Last Updated:** November 27, 2025  
**Status:** Production Ready 🚀
