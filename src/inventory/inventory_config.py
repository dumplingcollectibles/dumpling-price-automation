import os

class InventoryConfig:
    """
    Configuration for inventory management including source mappings,
    condition multipliers, and Shopify sync rules.
    """
    
    # ----------------------------------------------------------------------
    # Business Rules (Pricing)
    # ----------------------------------------------------------------------
    USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))
    MARKUP = float(os.getenv('MARKUP', '1.10'))
    
    # ----------------------------------------------------------------------
    # Condition & Source Enumerations
    # ----------------------------------------------------------------------
    VALID_CONDITIONS = ['NM', 'LP', 'MP', 'HP', 'DMG']
    
    CONDITION_MULTIPLIERS = {
        'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35
    }
    
    VALID_SOURCES_ADD = [
        'buylist', 'wholesale', 'opening', 'personal', 'trade', 
        'gift', 'return', 'other'
    ]
    
    VALID_REASONS_REMOVE = [
        'sold_ebay', 'sold_other', 'damaged', 'theft', 
        'lost', 'returned', 'other'
    ]
    
    # Fuzzy mappings from user input to canonical types
    SOURCE_MAPPINGS = {
        'buy': 'buylist', 'customer': 'buylist', 'purchase': 'buylist',
        'bulk': 'wholesale', 'distributor': 'wholesale', 'supplier': 'wholesale',
        'open': 'opening', 'pack': 'opening', 'booster': 'opening',
        'pulled': 'opening', 'mine': 'personal', 'collection': 'personal',
        'traded': 'trade', 'swap': 'trade'
    }

    CONDITION_VARIATIONS = {
        'NEAR MINT': 'NM', 'NEARMINT': 'NM', 'MINT': 'NM', 'M': 'NM',
        'LIGHTLY PLAYED': 'LP', 'LIGHT PLAY': 'LP',
        'MODERATELY PLAYED': 'MP', 'MODERATE PLAY': 'MP',
        'HEAVILY PLAYED': 'HP', 'HEAVY PLAY': 'HP',
        'DAMAGED': 'DMG', 'DAMAGE': 'DMG', 'D': 'DMG'
    }

inventory_config = InventoryConfig()
