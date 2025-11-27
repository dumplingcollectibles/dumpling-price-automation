# Dumpling Collectibles - Automation Suite

Automated tools for managing a Pokémon card e-commerce business on Shopify.

---

## 🎯 What This Does

Complete automation for:
- ✅ Daily price updates from market data
- ✅ Product uploads to Shopify
- ✅ Inventory management with cost tracking
- ✅ Automatic Shopify sync

---

## 📦 Features

### **1. Price Automation** 
**Location:** Root directory

- Daily price updates from PokemonTCG API
- Buylist pricing calculation
- Shopify sync
- Email reports

**Files:**
- `price_update_ultra_conservative.py` - Main price update script
- `.github/workflows/daily-price-update.yml` - Daily automation

**Usage:**
```bash
# Manual run
python price_update_ultra_conservative.py

# Automatic (GitHub Actions)
Runs daily at 3 AM EST
```

---

### **2. Product Upload**
**Location:** Root directory

- Bulk product creation
- Multi-condition variants (NM/LP/MP/HP/DMG)
- Set-based uploads
- Draft product creation

**Files:**
- `bulk_upload_corrected.py` - Main upload script
- `.github/workflows/product-upload-manual.yml` - Manual trigger workflow

**Usage:**
```bash
# Upload specific sets
python bulk_upload_corrected.py

# Via GitHub Actions
Use workflow_dispatch with set codes
```

---

### **3. Inventory Management** ⭐ **NEW!**
**Location:** `inventory/` folder

- Single card entry (interactive)
- Bulk CSV upload
- Weighted average cost tracking
- Complete audit trail
- Shopify inventory sync

**Files:**
- `inventory/add_inventory_single.py` - One-by-one entry
- `inventory/add_inventory_bulk.py` - CSV batch upload
- `inventory/csv_validator.py` - Validation helper
- `inventory/test_inventory_setup.py` - Setup checker

**Usage:**
```bash
# Single card
python inventory/add_inventory_single.py

# Bulk upload
python inventory/add_inventory_bulk.py buylist.csv
```

**See:** [inventory/README.md](inventory/README.md) for full documentation

---

## 🚀 Quick Start

### **1. Clone Repository**

```bash
git clone https://github.com/yourusername/dumpling-price-automation.git
cd dumpling-price-automation
```

### **2. Install Dependencies**

```bash
pip install -r requirements.txt
```

### **3. Configure Environment**

Create `.env` file:

```bash
# Database
NEON_DB_URL=postgresql://user:pass@host/db?sslmode=require

# Shopify
SHOPIFY_SHOP_URL=https://your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx
SHOPIFY_LOCATION_ID=123456789
SHOPIFY_API_VERSION=2025-01

# PokemonTCG API
POKEMONTCG_API_URL=https://api.pokemontcg.io/v2
TCG_API_KEY=your_api_key

# Email (for price update reports)
ZOHO_EMAIL=your-email@example.com
ZOHO_APP_PASSWORD=your_app_password

# Pricing
USD_TO_CAD=1.35
MARKUP=1.10
```

### **4. Test Setup**

```bash
# Check database
python inventory/test_inventory_setup.py

# Test price update (dry run)
python price_update_ultra_conservative.py
```

---

## 📁 Repository Structure

```
dumpling-price-automation/
├── .github/
│   └── workflows/
│       ├── daily-price-update.yml        # Automated daily price sync
│       └── product-upload-manual.yml     # Manual product upload trigger
│
├── inventory/                            # ⭐ Inventory management
│   ├── add_inventory_single.py           # Single card entry
│   ├── add_inventory_bulk.py             # Bulk CSV upload
│   ├── csv_validator.py                  # Validation module
│   ├── test_inventory_setup.py           # Setup test
│   ├── sample_inventory_upload.csv       # CSV template
│   └── README.md                         # Full documentation
│
├── price_update_ultra_conservative.py    # Price update script
├── bulk_upload_corrected.py              # Product upload script
├── requirements.txt                      # Python dependencies
├── .env.example                          # Environment template
├── .gitignore                            # Git ignore rules
└── README.md                             # This file
```

---

## 🔄 Typical Workflows

### **Workflow 1: New Product Line**

```bash
# 1. Upload products (creates cards + variants)
python bulk_upload_corrected.py

# 2. Add inventory
python inventory/add_inventory_bulk.py wholesale_order.csv

# Done! Products are live with inventory
```

---

### **Workflow 2: Customer Buylist**

```bash
# 1. Add inventory from buylist
python inventory/add_inventory_bulk.py buylist_customer_john.csv

# If some cards not in DB:
# 2. Upload missing products
python bulk_upload_corrected.py

# 3. Re-run buylist upload
python inventory/add_inventory_bulk.py failed_buylist_customer_john_TIMESTAMP.csv

# Done! Inventory updated, Shopify synced
```

---

### **Workflow 3: Pack Opening**

```bash
# Add cards one by one interactively
python inventory/add_inventory_single.py

# Or create CSV of pulls and bulk upload
python inventory/add_inventory_bulk.py pack_opening_session.csv
```

---

### **Workflow 4: Daily Operations**

```
3 AM EST: Price update runs automatically (GitHub Actions)
  ↓
Email report sent with changes
  ↓
Shopify prices updated
  ↓
Buylist prices recalculated
```

---

## 🎯 Business Logic

### **Pricing Tiers**

| Market Value | Cash Buylist | Credit Buylist |
|--------------|--------------|----------------|
| $0 - $49.99 | 60% | 70% |
| $50 - $99.99 | 70% | 80% |
| $100+ | 75% | 85% |

**Condition Modifiers (Singles):**
- NM: 100% of base
- LP: 80% of base
- MP: 60% of base
- HP: 40% of base
- DMG: 20% of base

### **Weighted Average Cost**

```
Old: 2 cards @ $80 = $160
New: 3 cards @ $90 = $270
─────────────────────────────
Total: 5 cards = $430
WAC: $430 ÷ 5 = $86.00/card
```

---

## 📊 Database Schema

**Tables:**
- `cards` - Card metadata
- `products` - Shopify products
- `variants` - Condition-based SKUs
- `inventory_transactions` - Complete audit trail
- `users` - Customer directory
- `orders` - Order history
- `buy_offers` - Buylist submissions
- `store_credit_ledger` - Credit tracking

**See:** `dumpling-db-schema.md` for complete schema

---

## 🔐 Security

- **Never commit `.env`** - Listed in `.gitignore`
- **GitHub Secrets** - Used for Actions workflows
- **Parameterized queries** - SQL injection prevention
- **API tokens** - Never logged or exposed

---

## 🧪 Testing

### **Price Update:**
```bash
python price_update_ultra_conservative.py
# Check: Email report, Shopify prices updated
```

### **Product Upload:**
```bash
python bulk_upload_corrected.py
# Check: Draft products in Shopify
```

### **Inventory:**
```bash
python inventory/test_inventory_setup.py
python inventory/add_inventory_single.py
python inventory/add_inventory_bulk.py inventory/sample_inventory_upload.csv
```

---

## 📈 Performance

**Price Updates:**
- ~445 cards
- 2.7 hours (ultra-conservative mode)
- Runs nightly, no impact on operations

**Product Uploads:**
- ~100 cards/set
- 3-5 minutes per set
- Manual trigger as needed

**Inventory:**
- Single entry: 1-2 min/card
- Bulk upload: 1-2 sec/card
- **50 cards: 100 min → 2 min (95% faster!)**

---

## 🚨 Troubleshooting

### **Database Connection Failed**
```bash
# Check NEON_DB_URL in .env
# Must end with ?sslmode=require
```

### **Shopify Sync Failed**
```bash
# Verify .env has:
# SHOPIFY_SHOP_URL
# SHOPIFY_ACCESS_TOKEN
# SHOPIFY_LOCATION_ID
```

### **GitHub Actions Failing**
```bash
# Check GitHub Secrets:
# Repository → Settings → Secrets and variables → Actions
# Verify all required secrets are set
```

### **Email Reports Not Sending**
```bash
# Use Zoho App Password (not account password)
# Generate at: accounts.zoho.com → Security → App Passwords
```

---

## 📚 Documentation

**Inventory System:**
- [inventory/README.md](inventory/README.md) - Complete guide
- Full workflow documentation
- CSV format reference
- Troubleshooting

**Database:**
- `dumpling-db-schema.md` - Complete schema
- Table relationships
- Business logic

**Business Context:**
- `dumpling-claude-context.md` - Business requirements
- Pricing strategy
- Product categories

---

## 🗓️ Automation Schedule

**Daily (GitHub Actions):**
- 3:00 AM EST - Price updates

**Manual (On Demand):**
- Product uploads
- Inventory additions

---

## 🎯 Roadmap

### **Phase 1: Foundation** ✅ **COMPLETE**
- [x] Price automation
- [x] Product uploads
- [x] Inventory management

### **Phase 2: Viewing & Reports** (Next)
- [ ] View inventory script
- [ ] Inventory history viewer
- [ ] Profit reports
- [ ] Low stock alerts

### **Phase 3: Order Integration**
- [ ] Shopify order sync
- [ ] Auto-reduce inventory
- [ ] Revenue tracking

### **Phase 4: Buylist System**
- [ ] Customer buylist form
- [ ] Quote generation
- [ ] Approval workflow
- [ ] Gift card issuance

### **Phase 5: Web Interface**
- [ ] Dashboard
- [ ] Team collaboration
- [ ] Role-based permissions
- [ ] Mobile responsive

---

## 📊 System Stats

**Scripts:** 8 production scripts
**Workflows:** 2 GitHub Actions
**Documentation:** 10+ guide files
**Lines of Code:** ~2,500 lines
**Time Saved:** ~165 hours/year

---

## ✅ Production Status

| Component | Status |
|-----------|--------|
| Price Updates | ✅ Production |
| Product Uploads | ✅ Production |
| Inventory (Single) | ✅ Production |
| Inventory (Bulk) | ✅ Production |
| GitHub Actions | ✅ Production |
| Email Reports | ✅ Production |

---

## 🆘 Support

**Issues:**
1. Check documentation first
2. Review error messages (detailed)
3. Test with sample files
4. Check `.env` configuration

**Common Fixes:**
- Database: Verify connection string
- Shopify: Check API credentials
- GitHub: Verify secrets configured
- Email: Use app password, not account password

---

## 📝 Version History

**v2.1** (Current - Nov 2025)
- ✅ Complete inventory management system
- ✅ Bulk CSV upload with validation
- ✅ Failed rows export
- ✅ Removed slow auto-product creation
- ✅ WAC calculation
- ✅ Full audit trail

**v2.0** (Nov 2025)
- ✅ Single card inventory entry
- ✅ Shopify inventory sync
- ✅ GitHub Actions workflows

**v1.0** (Nov 2025)
- ✅ Price automation
- ✅ Product uploads
- ✅ Database integration

---

**Built for:** Dumpling Collectibles  
**Platform:** Shopify + Neon PostgreSQL  
**Location:** Canada  
**Last Updated:** November 27, 2025  
**Status:** Production Ready 🚀
