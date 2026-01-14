-- Migration: Add price_history table
-- Purpose: Track daily market prices for cards in inventory
-- Date: 2025-01-15

-- Create price_history table
CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    condition VARCHAR(10) NOT NULL,
    market_price_usd DECIMAL(10,2),
    market_price_cad DECIMAL(10,2),
    suggested_price_cad DECIMAL(10,2),
    source VARCHAR(50) DEFAULT 'pokemontcg_io',
    checked_at TIMESTAMP DEFAULT NOW(),
    
    -- Prevent duplicate entries for same card/condition/time
    CONSTRAINT unique_price_check UNIQUE (card_id, condition, DATE(checked_at))
);

-- Index for fast lookup by card and condition
CREATE INDEX IF NOT EXISTS idx_price_history_card_lookup 
    ON price_history(card_id, condition, checked_at DESC);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_price_history_date 
    ON price_history(checked_at DESC);

-- Index for recent data (last 90 days) - most common queries
CREATE INDEX IF NOT EXISTS idx_price_history_recent 
    ON price_history(checked_at DESC) 
    WHERE checked_at > NOW() - INTERVAL '90 days';

-- Index for card_id only (for joins)
CREATE INDEX IF NOT EXISTS idx_price_history_card 
    ON price_history(card_id);

-- Comments for documentation
COMMENT ON TABLE price_history IS 'Daily market price tracking for cards with inventory';
COMMENT ON COLUMN price_history.market_price_usd IS 'Market price from TCGPlayer in USD';
COMMENT ON COLUMN price_history.market_price_cad IS 'Market price converted to CAD';
COMMENT ON COLUMN price_history.suggested_price_cad IS 'Suggested selling price (market × markup)';
COMMENT ON COLUMN price_history.source IS 'Data source (pokemontcg_io, tcgplayer, etc)';
COMMENT ON COLUMN price_history.checked_at IS 'When this price was recorded';
