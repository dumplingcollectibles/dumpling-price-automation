import os

class PricingConfig:
    """
    Mathematical configuration layer exclusively for the Pricing Engine domain.
    Abstracts out thresholds and matrices for easy modification without 
    touching the complex python execution processes.
    """

    # ----------------------------------------------------------------------
    # Core Engine Application Thresholds (Triggers Shopify Syncs)
    # ----------------------------------------------------------------------
    MIN_PRICE_CHANGE_DOLLARS = float(os.getenv('MIN_PRICE_CHANGE_DOLLARS', '0.50'))
    MIN_PRICE_CHANGE_PERCENT = float(os.getenv('MIN_PRICE_CHANGE_PERCENT', '5.0'))
    BIG_CHANGE_DOLLARS = float(os.getenv('BIG_CHANGE_DOLLARS', '10.0'))
    BIG_CHANGE_PERCENT = float(os.getenv('BIG_CHANGE_PERCENT', '20.0'))
    
    # ----------------------------------------------------------------------
    # Post-Calculation Reporting Thresholds (Weekly Delta Filters)
    # ----------------------------------------------------------------------
    REPORTING_MIN_CHANGE_DOLLARS = float(os.getenv('REPORTING_MIN_CHANGE_DOLLARS', '2.00'))
    REPORTING_MIN_CHANGE_PERCENT = float(os.getenv('REPORTING_MIN_CHANGE_PERCENT', '5.0'))

    # ----------------------------------------------------------------------
    # Selling Market Margin Matrices
    # ----------------------------------------------------------------------
    CONDITION_MULTIPLIERS = {
        'NM': 1.00, 'LP': 0.80, 'MP': 0.65, 'HP': 0.50, 'DMG': 0.35
    }
    
    # ----------------------------------------------------------------------
    # Buylist (C2B) Payout Cash-Out Matrices
    # ----------------------------------------------------------------------
    # Based on the underlying market value of the card (CAD)
    BUYLIST_NM_UNDER_50_CASH = 0.60
    BUYLIST_NM_UNDER_50_CREDIT = 0.70
    
    BUYLIST_NM_50_TO_100_CASH = 0.70
    BUYLIST_NM_50_TO_100_CREDIT = 0.80
    
    BUYLIST_NM_OVER_100_CASH = 0.75
    BUYLIST_NM_OVER_100_CREDIT = 0.85
    
    # Modifier of condition value relative to its NM payout value
    BUYLIST_LP_MODIFIER = 0.75
    BUYLIST_MP_MODIFIER = 0.50
    BUYLIST_UNSUPPORTED_CONDITIONS = ['HP', 'DMG']

pricing_config = PricingConfig()
