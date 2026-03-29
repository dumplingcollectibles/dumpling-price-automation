import os

class StoreCreditConfig:
    """
    Configuration layer for Store Credit constants and business strings.
    Extracts hardcoded transaction constraints out of the controllers.
    """
    
    DEFAULT_TRANSACTION_TYPE = 'adjustment'
    
    # Valid transaction types defined by the database schema or business rules
    VALID_TRANSACTION_TYPES = [
        'buylist_payout', 
        'refund', 
        'adjustment', 
        'promotion', 
        'order_payment'
    ]
    
    # UI Dictionary for nicely presenting transaction types in reports/CLI
    TRANSACTION_TYPE_DESCRIPTIONS = {
        'buylist_payout': '💰 Buylist Payout',
        'order_payment': '🛒 Order Payment',
        'adjustment': '✏️  Adjustment',
        'refund': '↩️  Refund',
        'promotion': '🎉 Promotion'
    }

    # Dynamic format strings
    DEFAULT_GIFT_CARD_NOTE_TEMPLATE = os.getenv(
        'DEFAULT_GIFT_CARD_NOTE_TEMPLATE', 
        "Store credit issued for {email}"
    )

store_credit_config = StoreCreditConfig()
