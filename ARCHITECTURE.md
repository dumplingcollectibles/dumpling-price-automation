# Dumpling Collectibles - Complete Architecture & System Spec

This document details the exact state of the Dumpling Price Automation system today. 

**System Context:** This repository represents a completely decoupled, standalone web application that operates alongside the main Dumpling Collectibles Shopify storefront. Its primary responsibilities are acting as a dynamic nightly pricing engine, maintaining an internal inventory ledger, and hosting a custom "Buylist" web portal (C2B) that handles dynamic customer sale quotes—a feature Shopify natively lacks.

## 1. High-Level Architecture Overview

```mermaid
graph TD
    %% Environments
    subgraph Operations [CLI Controllers]
        PricingJob["pricing_job.py (Job)"]
        HistoryJob["price_history_job.py (Job)"]
        StoreCreditCLI["store_credit_cli.py (CLI)"]
        InventoryBulkCLI["inventory_cli_bulk_add.py (CLI)"]
        InventorySingleCLI["inventory_cli_single_adjust.py (CLI)"]
    end

    subgraph Frontend [Static Frontend]
        UI["Buylist Web App (HTML/JS)"]
    end

    subgraph API [Flask Controllers]
        BuylistAPI["buylist_app.py (Flask)"]
        WebhookServer["webhook_server.py (Flask)"]
    end

    subgraph DomainServices [Service Layer]
        PricingService["PricingService"]
        HistoryService["PriceHistoryService"]
        StoreCreditService["StoreCreditService"]
        BuylistService["BuylistService"]
        WebhookService["WebhookService"]
        InventoryService["InventoryService"]
        PricingReporter["PricingReporter"]
        BuylistReporter["BuylistReporter"]
        StoreCreditReporter["StoreCreditReporter"]
    end

    subgraph External [External APIs]
        Shopify[("Shopify API")]
        PokemonTCG[("PokémonTCG API")]
        Brevo[("Brevo & Zoho SMTP")]
        Slack[("Slack Webhook")]
    end

    subgraph DB [Database]
        Postgres[("Neon PostgreSQL")]
    end

    %% Internal Workflows
    UI -->|Submit Quote| BuylistAPI
    BuylistAPI -->|R/W Quotes, Users| BuylistService
    BuylistService -->|R/W| Postgres
    BuylistService -->|Notify| BuylistReporter
    BuylistReporter -->|Post Email| Brevo

    Shopify -.->|Order Creation Webhook| WebhookServer
    WebhookServer -->|Sync Inventory/Ledger| WebhookService
    WebhookService -->|R/W| Postgres
    WebhookService -->|Fetch Full Order| Shopify
    WebhookService -->|Record Ledger| StoreCreditService

    DailyPriceCron --> PricingJob
    PricingJob --> PricingService
    PricingService -->|Fetch Market Prices| PokemonTCG
    PricingService -->|Update DB Models| Postgres
    PricingService -->|PUT Variant Price| Shopify
    
    PricingJob --> PricingReporter
    PricingReporter -->|Email Report| Brevo
    
    DailyPriceCron -.-> HistoryJob
    HistoryJob --> HistoryService
    HistoryService -->|Snapshot variants to price_history| Postgres
    
    StoreCreditCLI --> StoreCreditService
    StoreCreditService -->|Gift Card API| Shopify
    StoreCreditService -->|Issue Credit Ledger| Postgres
```

## 2. Database Schema (PostgreSQL)

Below is the Entity-Relationship (ER) diagram for the main tables governing inventory, users, Shopify syncing, and the buylist.

```mermaid
erDiagram
    users ||--o{ orders : places
    users ||--o{ store_credit_ledger : has
    users ||--o{ buy_offers : submits

    cards ||--o{ products : has
    cards ||--o{ price_history : tracks
    products ||--o{ variants : contains
    
    orders ||--o{ order_items : includes
    variants ||--o{ order_items : sold_as
    variants ||--o{ inventory_transactions : log
    
    buy_offers ||--|{ buy_offer_items : includes
    cards ||--|{ buy_offer_items : requested_for

    users {
        SERIAL id PK
        VARCHAR email
        VARCHAR name
        VARCHAR shopify_customer_id
        JSONB address
        TIMESTAMP created_at
    }

    cards {
        SERIAL id PK
        JSONB external_ids
        VARCHAR name
        VARCHAR set_code
        VARCHAR set_name
        VARCHAR number
        VARCHAR img_url
    }

    products {
        SERIAL id PK
        INT card_id FK
        VARCHAR shopify_product_id
    }

    variants {
        SERIAL id PK
        INT product_id FK
        VARCHAR shopify_variant_id
        VARCHAR condition
        DECIMAL market_price
        DECIMAL price_cad
        DECIMAL buy_cash
        DECIMAL buy_credit
        INT inventory_qty
        DECIMAL cost_basis_avg
        TIMESTAMP price_updated_at
    }

    orders {
        SERIAL id PK
        INT user_id FK
        VARCHAR shopify_order_id
        TIMESTAMP order_date
        DECIMAL order_total
        DECIMAL order_amount_cash
        DECIMAL order_amount_credit
        VARCHAR payment_method
        VARCHAR status
        JSONB gift_card_codes
        DECIMAL gift_card_amount_used
    }

    order_items {
        SERIAL id PK
        INT order_id FK
        INT variant_id FK
        INT quantity
        DECIMAL unit_price
        DECIMAL subtotal
    }

    inventory_transactions {
        SERIAL id PK
        INT variant_id FK
        VARCHAR transaction_type
        INT quantity
        DECIMAL unit_cost
        VARCHAR reference_type
        INT reference_id
        TIMESTAMP created_at
    }

    buy_offers {
        SERIAL id PK
        INT user_id FK
        VARCHAR cash_or_credit
        DECIMAL quoted_total_cad
        VARCHAR status
        TIMESTAMP expires_at
    }

    buy_offer_items {
        SERIAL id PK
        INT buy_offer_id FK
        INT card_id FK
        VARCHAR condition
        INT quantity
        DECIMAL quoted_price_per_unit
    }

    store_credit_ledger {
        SERIAL id PK
        INT user_id FK
        DECIMAL amount
        VARCHAR transaction_type
        VARCHAR reference_type
        INT reference_id
        DECIMAL balance_after
        VARCHAR shopify_gift_card_code
        TIMESTAMP created_at
    }
    
    price_history {
        SERIAL id PK
        INT card_id FK
        VARCHAR condition
        DECIMAL market_price_usd
        DECIMAL market_price_cad
        DECIMAL suggested_price_cad
        TIMESTAMP checked_at
    }
```

## 3. API Data Providers & Critical Constraints

Because we rely on external services that aggressively rate-limit, the codebase incorporates varying levels of concurrency and back-off delays. These bottlenecks dictate our update speeds and dictate how the nightly automation functions.

### A. PokémonTCG API (`api.pokemontcg.io`)
*   **Purpose:** Fetches market prices (specifically extracting TCGPlayer normal/holofoil/reverse) to calculate base CAD pricing.
*   **Constraints:** High rate-limiting. A linear script (without API Keys or when throttled) requires progressive sleep times. `pricing_job.py` incorporates these constraints to prevent complete lockouts (`HTTP 429: Too Many Requests`).
*   **Structure:** We issue individual `GET /v2/cards/{external_id}` calls per card.

### B. Shopify API
*   **Purpose:** Acts as our source of truth for POS and eCommerce inventory.
*   **Constraints:** Shopify has REST Admin API bucket limits (typically 2 requests/sec on basic plans).
*   **Structure:** 
    *   **Price Syncing:** Our scripts update variant prices by hitting `PUT /admin/api/2025-01/variants/{id}.json` directly. This happens sequentially per variant, with manual `sleep(0.3)` constraints programmed into the `PricingService`.
    *   **Webhooks:** During an order webhook, we must fetch the API at `GET /admin/api/2025-01/orders/{id}.json` to extract deep gift-card transaction data missing from the raw webhook payload.

### C. Email Providers (Brevo / Zoho)
*   **Structure:** Used dynamically. The Flask APIs (`buylist_app.py`) natively execute internal/customer emails via the **Brevo REST API (`POST /v3/smtp/email`)**. The automated Python scripts use standard Python `smtplib` via **Zoho SMTP or Brevo SMTP relays** to construct and send HTML strings representing price movement reports.

### D. Slack Notifications
*   **Purpose:** Simple price change monitoring.
*   **Structure:** Scripts like `scripts/slack_sender.py` utilize `requests.post` to a single `SLACK_WEBHOOK_URL` to notify administration of distinct inventory value impacts and pricing adjustments.

---

## 4. Domain Services & Background Jobs

All primary autonomous processes are organized into 3-tier domains and run through **GitHub Actions** (`workflows/`).

### 4.1 Pricing Engine Domain
*   **Controller:** `src/pricing_engine/pricing_job.py`
    *   **Schedule:** Runs via `daily-price-update.yml` (Midnight EST).
    *   **Execution:** Supports `all`, `bucket` (e.g. "$50-100"), or `series` (e.g. "Base Set") modes.
    *   **Concurrency:** Utilizes `ThreadPoolExecutor` with 3 threads and a `shopify_lock` to respect rate limits.
*   **Service Layer:** `src/pricing_engine/pricing_service.py`
    *   **Logic:** Handles marker price extraction, markup math, and buylist cash/credit matrices.
    *   **Data Access:** Manages isolated Postgres connections and Shopify API variant updates.
*   **Configuration:** `src/pricing_engine/pricing_config.py` isolates all business rules (thresholds, multipliers).

### 4.2 Price History & Analysis Domain
*   **Controller:** `src/pricing_engine/price_history_job.py`
    *   **Capabilities:** `snapshot` (daily price tracking) and `weekly` (delta reporting).
*   **Service Layer:** `src/pricing_engine/price_history_service.py`
    *   **Logic:** Calculates 7-day price deltas and inventory value impact summaries.

### 4.3 Store Credit Domain
*   **Controller:** `src/store_credit/store_credit_cli.py`
    *   **Trigger:** Manual via `issue-store-credit.yml` or CLI.
    *   **Capabilities:** `check` (balance/history) and `issue` (adjustments/buylist payouts).
*   **Service Layer:** `src/store_credit/store_credit_service.py`
    *   **Logic:** Orchestrates Shopify Gift Card creation, database ledger entries, and customer email notifications.
*   **Configuration:** `src/store_credit/store_credit_config.py` defines valid transaction types and note templates.

### 4.7 Inventory Domain
*   **Controllers:** 
    *   `src/inventory/inventory_cli_single_adjust.py` (Manual CLI adjustment)
    *   `src/inventory/inventory_cli_bulk_add.py` (CSV bulk upload)
    *   `src/inventory/inventory_cli_shopify_sync.py` (Shopify drift repair & audit)
*   **Service Layer:** `src/inventory/inventory_service.py`
    *   **Logic:** Central engine for Weighted Average Cost (WAC) math, PokemonTCG API fetching, Shopify product orchestration, and inventory syncing.
*   **Configuration:** `src/inventory/inventory_config.py` defines condition multipliers (NM=1.00, DMG=0.35), buylist payout matrices, and market price floors.

### 4.8 Notifications Layer
*   **Service:** `src/notifications/pricing_reporter.py`
    *   **HTML Generation:** Centralized logic for building the beautiful HTML email reports for price updates.
*   **Service:** `src/notifications/buylist_reporter.py`
    *   **HTML Generation:** Encapsulates specialized customer quotes and internal team alerts.
*   **Service:** `src/notifications/store_credit_reporter.py`
    *   **HTML Generation:** Builds the gift card receipt and customer balance notification HTML.

---

## 5. User Interaction Flows (Customer Facing)

*Note: Standard customer eCommerce purchases (B2C) are fundamentally handled on the external Shopify storefront. This codebase's custom Javascript frontend exists strictly to handle the complex C2B (Customer-to-Business) "Buylist" flow, allowing users to interactively search and submit lists of cards for immediate cash or store credit quotes based on the natively tracked market pricing matrix.*

### 5.1 Buylist Quoting (`frontend/` & `api/buylist_app.py`)
1.  **Discovery:** User loads the Vanilla JS site and queries a card name. The `GET /api/cards/search` endpoint only returns cards actively bought by checking if `v.buy_cash > 0` and groups condition variables (`NM`, `LP`, etc.).
2.  **Cart Assembly:** User selects condition/quantities and chooses a preferred payout method (**Cash** or **Store Credit**).
3.  **Submission:** The `POST /api/buylist/submit` endpoint handles the payload:
    *   Creates/fetches user information in the DB using their email.
    *   Verifies against the `variants` table to pull the live `buy_cash` or `buy_credit` value that was cached by the nightly price automation job.
    *   Calculates real-time price sub-totals for each line item.
    *   Inserts into the `buy_offers` ledger (Quote ID) and `buy_offer_items` for individual cards.
    *   Pings Brevo Email API to notify internal team and email the customer the quote.

### 5.2 Webhook Processing (`webhook/webhook_server.py`)
1.  **Receipt:** Shopify hits `POST /webhooks/shopify/orders/create` upon any checkout.
2.  **Validation:** The payload is verified via `X-Shopify-Hmac-Sha256` signature using our DB `SHOPIFY_WEBHOOK_SECRET`.
3.  **Transaction Resolution:**
    *   If payment gateways specify `gift_card`, the script launches a raw `GET` fetch against the Shopify REST API for deeper sub-transaction insight (the webhook payload alone obscures used card codes).
4.  **Database Syncing:**
    *   Logs the order payload into `orders` and subtracts `inventory_qty` internally in `variants`.
    *   Creates `inventory_transactions` rows representing the sale tracking the `cost_basis_avg`.
    *   If a gift card was used, a negative flow is entered into `store_credit_ledger` for that user.

---

## 6. Required Transitions For Re-Write

When porting this logic to a structured backend (FastAPI/Django) and React UI, specific focus must be directed at our **API rate constraints**:

1.  **Pricing Background Jobs:** The `pricing_job.py` architecture relies heavily on rudimentary thread pausing (`time.sleep`) and linear operations. It restricts our capability to add Multi-API aggregates. We must use a dedicated queue worker (like Celery/RabbitMQ) with managed retries (e.g. `ExponentialBackoff` algorithms without blocking worker threads).
2.  **Bulk Shopify Updates:** Modulating prices via individual `PUT /variants/{id}.json` triggers maximum rate limits fast. Shopify GraphQL API `productVariantsBulkUpdate` mutations should be used to hit dozens of variant prices in a single API roundtrip.
3.  **Missing Files Integrity:** Investigate the cron discrepancy where `daily-price-update.yml` requests the new `pricing_job.py` to assert the correct execution flow for today's market conditions.
