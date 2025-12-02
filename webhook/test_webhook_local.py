"""
Local Webhook Testing Script

Test your webhook server locally before deploying to Render.

This simulates a Shopify webhook and lets you verify:
- Database connection works
- Order processing logic works
- Inventory updates correctly
"""

import json
import requests
from datetime import datetime

# Sample Shopify order webhook payload
SAMPLE_ORDER = {
    "id": 9999999999,
    "order_number": 1001,
    "created_at": datetime.now().isoformat(),
    "customer": {
        "id": 123456789,
        "email": "test@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "default_address": {
            "address1": "123 Main St",
            "city": "Toronto",
            "province": "Ontario",
            "zip": "M5V 3A8",
            "country": "Canada"
        }
    },
    "line_items": [
        {
            "variant_id": "YOUR_SHOPIFY_VARIANT_ID_HERE",  # ← Change this!
            "title": "Charizard - Base Set - NM",
            "quantity": 1,
            "price": "100.00"
        }
    ],
    "total_price": "113.00",
    "subtotal_price": "100.00",
    "total_tax": "13.00",
    "total_shipping_price_set": {
        "shop_money": {
            "amount": "0.00"
        }
    },
    "payment_gateway_names": ["credit_card"]
}


def test_webhook_locally():
    """
    Test webhook by sending to local server
    
    Make sure server is running:
    python webhook_server.py
    """
    print("=" * 70)
    print("🧪 LOCAL WEBHOOK TEST")
    print("=" * 70)
    print()
    
    # Make sure to update the variant_id above with a real one from your database!
    print("⚠️  IMPORTANT: Update SAMPLE_ORDER above with a real shopify_variant_id")
    print("   from your database before running!")
    print()
    
    url = "http://localhost:5000/webhooks/shopify/orders/create"
    
    print(f"Sending test webhook to: {url}")
    print()
    
    try:
        response = requests.post(
            url,
            json=SAMPLE_ORDER,
            headers={
                'Content-Type': 'application/json',
                'X-Shopify-Shop-Domain': 'test-store.myshopify.com',
                'X-Shopify-Topic': 'orders/create',
                'X-Shopify-Hmac-Sha256': 'test'  # Signature check disabled for local testing
            },
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        print()
        
        if response.status_code == 200:
            print("✅ Webhook processed successfully!")
            print()
            print("Check your database:")
            print("  - New order in `orders` table")
            print("  - Reduced inventory in `variants` table")
            print("  - New transaction in `inventory_transactions` table")
        else:
            print("❌ Webhook failed!")
            print(f"   Error: {response.json()}")
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server!")
        print()
        print("Make sure server is running:")
        print("  python webhook_server.py")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_health_check():
    """Test that server is running"""
    print("=" * 70)
    print("🏥 HEALTH CHECK")
    print("=" * 70)
    print()
    
    url = "http://localhost:5000/health"
    
    try:
        response = requests.get(url, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        print()
        
        if response.status_code == 200:
            print("✅ Server is healthy!")
        else:
            print("⚠️  Server responded but might have issues")
            
    except requests.exceptions.ConnectionError:
        print("❌ Server not running!")
        print()
        print("Start server with:")
        print("  python webhook_server.py")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    import sys
    
    print()
    print("🧪 WEBHOOK TESTING TOOL")
    print()
    print("Options:")
    print("  [1] Health check (is server running?)")
    print("  [2] Test webhook (send sample order)")
    print("  [3] Exit")
    print()
    
    choice = input("Choice (1-3): ").strip()
    print()
    
    if choice == '1':
        test_health_check()
    elif choice == '2':
        test_webhook_locally()
    elif choice == '3':
        print("👋 Goodbye!")
    else:
        print("❌ Invalid choice")
