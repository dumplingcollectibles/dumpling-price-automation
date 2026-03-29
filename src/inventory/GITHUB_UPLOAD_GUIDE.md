# GitHub Upload Checklist & Instructions

Complete step-by-step guide to upload your inventory system to GitHub.

---

## 📋 Pre-Upload Checklist

- [ ] All files downloaded to your computer
- [ ] `.env` file is in `.gitignore` (DO NOT UPLOAD!)
- [ ] Credentials removed from any example files
- [ ] README files created
- [ ] Ready to push to GitHub

---

## 📥 Files to Download

### **Inventory Scripts (5 files):**
1. ✅ add_inventory_single.py
2. ✅ add_inventory_bulk.py
3. ✅ csv_validator.py
4. ✅ test_inventory_setup.py
5. ✅ sample_inventory_upload.csv

### **Documentation (2 files):**
6. ✅ inventory-README.md (rename to `README.md`)
7. ✅ main-README.md (rename to `README.md` for root)

---

## 🗂️ Folder Structure to Create

```
dumpling-price-automation/
├── .github/
│   └── workflows/
│       ├── daily-price-update.yml        (already there)
│       └── product-upload-manual.yml     (already there)
│
├── inventory/                            ← CREATE THIS FOLDER
│   ├── add_inventory_single.py           ← UPLOAD
│   ├── add_inventory_bulk.py             ← UPLOAD
│   ├── csv_validator.py                  ← UPLOAD
│   ├── test_inventory_setup.py           ← UPLOAD
│   ├── sample_inventory_upload.csv       ← UPLOAD
│   └── README.md                         ← UPLOAD (inventory-README.md)
│
├── price_update_ultra_conservative.py    (already there)
├── bulk_upload_corrected.py              (already there)
├── requirements.txt                      ← UPDATE
├── .gitignore                            ← CHECK
└── README.md                             ← UPDATE (main-README.md)
```

---

## 🚀 Step-by-Step Upload

### **Method A: GitHub Web Interface** (Easiest)

#### **Step 1: Create inventory folder**

1. Go to your GitHub repo
2. Click **"Add file"** → **"Create new file"**
3. In filename box, type: `inventory/README.md`
   - This creates the folder automatically!
4. Paste contents of `inventory-README.md`
5. Scroll down, commit:
   - Commit message: `Add inventory system README`
   - Click **"Commit new file"**

#### **Step 2: Upload inventory scripts**

For each script file:

1. Navigate to `inventory/` folder (click on it)
2. Click **"Add file"** → **"Upload files"**
3. Drag & drop OR click "choose your files":
   - `add_inventory_single.py`
   - `add_inventory_bulk.py`
   - `csv_validator.py`
   - `test_inventory_setup.py`
   - `sample_inventory_upload.csv`
4. Commit message: `Add inventory management scripts`
5. Click **"Commit changes"**

#### **Step 3: Update main README**

1. Go to root of repo (click repo name)
2. Click on `README.md`
3. Click **pencil icon** (Edit)
4. Replace entire contents with `main-README.md`
5. Commit message: `Update README with inventory system`
6. Click **"Commit changes"**

#### **Step 4: Update requirements.txt**

1. Go to root of repo
2. Click `requirements.txt`
3. Click **pencil icon** (Edit)
4. Make sure it has:
   ```
   psycopg2-binary==2.9.9
   requests==2.31.0
   python-dotenv==1.0.0
   ```
5. Commit message: `Update requirements for inventory system`
6. Click **"Commit changes"**

#### **Step 5: Verify .gitignore**

1. Click `.gitignore` in root
2. Make sure it includes:
   ```
   .env
   *.pyc
   __pycache__/
   .DS_Store
   *.log
   errors_*.csv
   failed_*.csv
   ```
3. If missing, edit and add them
4. Commit: `Update .gitignore`

---

### **Method B: Git Command Line** (For Advanced Users)

```bash
# 1. Clone your repo (if not already)
git clone https://github.com/yourusername/dumpling-price-automation.git
cd dumpling-price-automation

# 2. Create inventory folder
mkdir inventory

# 3. Copy files to inventory folder
cp ~/Downloads/add_inventory_single.py inventory/
cp ~/Downloads/add_inventory_bulk.py inventory/
cp ~/Downloads/csv_validator.py inventory/
cp ~/Downloads/test_inventory_setup.py inventory/
cp ~/Downloads/sample_inventory_upload.csv inventory/
cp ~/Downloads/inventory-README.md inventory/README.md

# 4. Update main README
cp ~/Downloads/main-README.md README.md

# 5. Update requirements.txt
echo "psycopg2-binary==2.9.9
requests==2.31.0
python-dotenv==1.0.0" > requirements.txt

# 6. Stage all changes
git add .

# 7. Commit
git commit -m "Add complete inventory management system"

# 8. Push to GitHub
git push origin main
```

---

## ✅ Verification Checklist

After upload, check:

- [ ] Navigate to `https://github.com/yourusername/dumpling-price-automation`
- [ ] See `inventory/` folder in file list
- [ ] Click into `inventory/` folder
- [ ] See all 6 files (5 scripts + README)
- [ ] Main README updated with inventory info
- [ ] `.gitignore` includes `.env`
- [ ] No sensitive data visible anywhere

---

## 🔐 CRITICAL: Security Check

**BEFORE UPLOADING - VERIFY:**

- [ ] `.env` file is NOT in repo
- [ ] No database passwords visible
- [ ] No Shopify tokens visible
- [ ] No API keys visible
- [ ] `.gitignore` includes `.env`

**If you accidentally upload `.env`:**

1. Delete the file from GitHub
2. **ROTATE ALL CREDENTIALS** (they're now compromised!)
   - Generate new Shopify access token
   - Change database password
   - Get new API keys
3. Update `.env` locally with new credentials
4. Never upload `.env` again

---

## 🧪 Testing After Upload

### **Option 1: Run Locally**

```bash
# Clone fresh from GitHub
git clone https://github.com/yourusername/dumpling-price-automation.git
cd dumpling-price-automation

# Install deps
pip install -r requirements.txt

# Copy your .env file
cp ~/path/to/your/.env .env

# Test
python inventory/test_inventory_setup.py
python inventory/add_inventory_single.py
```

### **Option 2: GitHub Actions** (Future)

You could create a workflow to run inventory scripts, but for now local is fine!

---

## 📁 Final Structure (What You Should See on GitHub)

```
dumpling-price-automation/
├── .github/
│   └── workflows/
│       ├── daily-price-update.yml
│       └── product-upload-manual.yml
├── inventory/                    ← NEW!
│   ├── README.md                 ← NEW!
│   ├── add_inventory_bulk.py     ← NEW!
│   ├── add_inventory_single.py   ← NEW!
│   ├── csv_validator.py          ← NEW!
│   ├── sample_inventory_upload.csv ← NEW!
│   └── test_inventory_setup.py   ← NEW!
├── .gitignore
├── README.md                     ← UPDATED!
├── bulk_upload_corrected.py
├── price_update_ultra_conservative.py
└── requirements.txt              ← UPDATED!
```

---

## 🎯 What You Get

**Benefits of GitHub:**
- ✅ Version control (track all changes)
- ✅ Backup (cloud storage)
- ✅ Collaboration (future team members)
- ✅ Documentation (README visible to all)
- ✅ Automation (GitHub Actions)
- ✅ Easy deployment (clone anywhere)

**Next Steps After Upload:**
1. Clone repo on any computer
2. Add `.env` file
3. Install dependencies
4. Run scripts!

---

## 🆘 Troubleshooting Upload

### **"File too large"**

GitHub has 100MB file limit. Your scripts are tiny, so this shouldn't happen.

### **"Repository not found"**

Check repo URL is correct:
`https://github.com/yourusername/dumpling-price-automation`

### **"Permission denied"**

Make sure you're logged into GitHub and have write access to the repo.

### **"Merge conflict"**

If someone else edited files:
1. Pull latest changes first: `git pull`
2. Resolve conflicts
3. Commit and push again

---

## 📝 Recommended Commit Messages

Good commit messages help track changes:

- ✅ `Add inventory management system`
- ✅ `Add bulk CSV upload script`
- ✅ `Update README with inventory docs`
- ✅ `Fix validation error in csv_validator`

❌ Avoid:
- `update`
- `fix`
- `changes`
- `asdf`

---

## 🎉 You're Done!

Once uploaded, you'll have:
- ✅ Complete backup of all scripts
- ✅ Version history
- ✅ Professional documentation
- ✅ Easy deployment to any computer
- ✅ Foundation for team collaboration

**Share the GitHub link and anyone can:**
1. Clone the repo
2. Add their `.env`
3. Start using the system!

---

## 🚀 Next: Running from GitHub

After upload, to use on any computer:

```bash
# 1. Clone
git clone https://github.com/yourusername/dumpling-price-automation.git

# 2. Navigate
cd dumpling-price-automation

# 3. Install
pip install -r requirements.txt

# 4. Configure
# Create .env file with your credentials

# 5. Test
python inventory/test_inventory_setup.py

# 6. Use!
python inventory/add_inventory_bulk.py buylist.csv
```

**That's it!** Your entire system is portable and backed up! 🎊

---

**Ready to upload?** Follow the steps above and let me know if you hit any issues! 😊
