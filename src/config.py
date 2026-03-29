import os
from dotenv import load_dotenv

# Automatically load environment variables from the nearest .env file
load_dotenv()

class Config:
    """Centralized configuration map for Dumpling Price Automation."""
    
    # ----------------------------------------------------------------------
    # Database
    # ----------------------------------------------------------------------
    DATABASE_URL = os.getenv('NEON_DB_URL') or os.environ.get('DATABASE_URL')
    
    # ----------------------------------------------------------------------
    # Shopify Integrations
    # ----------------------------------------------------------------------
    SHOPIFY_SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
    SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
    SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION', '2025-01')
    SHOPIFY_LOCATION_ID = os.getenv('SHOPIFY_LOCATION_ID')
    SHOPIFY_WEBHOOK_SECRET = os.getenv('SHOPIFY_WEBHOOK_SECRET')
    
    # ----------------------------------------------------------------------
    # Third-Party APIs (Pokemon TCG)
    # ----------------------------------------------------------------------
    POKEMONTCG_API_URL = os.getenv('POKEMONTCG_API_URL', 'https://api.pokemontcg.io/v2')
    TCG_API_KEY = os.getenv('TCG_API_KEY')
    
    # ----------------------------------------------------------------------
    # E-Commerce Rates & Margins
    # ----------------------------------------------------------------------
    USD_TO_CAD = float(os.getenv('USD_TO_CAD', '1.35'))
    MARKUP = float(os.getenv('MARKUP', '1.10'))
    
    # ----------------------------------------------------------------------
    # Notifications & Alerting
    # ----------------------------------------------------------------------
    EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'true').lower() == 'true'
    BREVO_API_KEY = os.getenv('BREVO_API_KEY')
    BREVO_EMAIL = os.getenv('BREVO_EMAIL')
    ZOHO_EMAIL = os.getenv('ZOHO_EMAIL')
    ZOHO_APP_PASSWORD = os.getenv('ZOHO_APP_PASSWORD')
    EMAIL_TO = os.getenv('EMAIL_TO', ZOHO_EMAIL)
    EMAIL_FROM = os.getenv('EMAIL_FROM', ZOHO_EMAIL)
    FROM_NAME = os.getenv('FROM_NAME', STORE_NAME)
    
    ZOHO_SMTP_HOST = os.getenv('ZOHO_SMTP_HOST', 'smtp.zoho.com')
    ZOHO_SMTP_PORT = int(os.getenv('ZOHO_SMTP_PORT', 587))
    
    SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

    # ----------------------------------------------------------------------
    # Application State
    # ----------------------------------------------------------------------
    STORE_NAME = os.getenv('STORE_NAME', 'Dumpling Collectibles')
    PORT = int(os.environ.get('PORT', 5000))

# Export a single active instance to be imported by the rest of the application
config = Config()
