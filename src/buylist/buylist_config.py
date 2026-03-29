import os

class BuylistConfig:
    """
    Configuration layer for Buylist business rules, expiration policies,
    and search constraints.
    """
    
    # ----------------------------------------------------------------------
    # Quoting & Expiration Rules
    # ----------------------------------------------------------------------
    QUOTE_EXPIRY_DAYS = int(os.getenv('BUYLIST_QUOTE_EXPIRY_DAYS', '7'))
    
    # ----------------------------------------------------------------------
    # Search Constraints
    # ----------------------------------------------------------------------
    SEARCH_LIMIT_DEFAULT = 20
    MIN_SEARCH_QUERY_LENGTH = 2
    
    # ----------------------------------------------------------------------
    # Notification Settings
    # ----------------------------------------------------------------------
    INTERNAL_CONTACT_EMAIL = os.getenv('BUYLIST_INTERNAL_EMAIL', 'buylist@dumplingcollectibles.com')
    
    SUBJECT_CUSTOMER_CONFIRMATION = "🎉 Buylist Quote Received - {store_name}"
    SUBJECT_INTERNAL_NOTIFICATION = "🔔 New Buylist Submission - Quote #{quote_id}"

    # Valid payout methods
    PAYOUT_METHODS = ['cash', 'credit']

buylist_config = BuylistConfig()
