"""
Pricing Engine Job Controller
Triggers daily market syncs by instantiating the PricingService concurrently.
Consolidates all previous series-based and bucket-based runner scripts.

Usage:
  python -m src.pricing_engine.pricing_job bucket "$50-100"
  python -m src.pricing_engine.pricing_job series "Base Set"
  python -m src.pricing_engine.pricing_job all
"""
import sys
import time
import threading
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from src.config import config
from src.pricing_engine.pricing_service import PricingService
from src.notifications.pricing_reporter import PricingReporter

# Shared execution lock to prevent Shopify API concurrent rate-limiting
shopify_lock = threading.Lock()
NUM_THREADS = 3

def process_card_group(cards, group_name):
    # Initializes its own stateless service per thread for safe Database mapping
    service = PricingService()
    
    local_stats = {
        'total_processed': 0, 'total_updated': 0, 'variants_updated': 0,
        'shopify_synced': 0, 'price_increases': 0, 'price_decreases': 0,
        'failed': 0, 'no_change': 0, 'big_changes': []
    }
    
    print(f"\n🧵 Thread '{group_name}' starting with {len(cards)} cards...")
    for i, card in enumerate(cards, 1):
        local_stats['total_processed'] += 1
        print(f"   [{group_name}] [{i}/{len(cards)}] {card['name']} ({card['set_code']}-{card['number']})...", end=' ', flush=True)
        
        external_ids = card['external_ids']
        pokemontcg_id = external_ids.get('pokemontcg_io') if external_ids else None
        
        if not pokemontcg_id:
            local_stats['failed'] += 1
            print(f" ❌ No API ID")
            continue
            
        market_usd = service.fetch_api_price(pokemontcg_id)
        if market_usd is None:
            local_stats['failed'] += 1
            print(f" ❌ API failed")
            continue
            
        base_market_cad = market_usd * config.USD_TO_CAD
        nm_selling_price = service.round_up_to_nearest_50_cents(base_market_cad * config.MARKUP)
        
        updated_variants = service.update_variants_in_database(card['card_id'], base_market_cad, nm_selling_price)
        
        if updated_variants:
            local_stats['total_updated'] += 1
            local_stats['variants_updated'] += len(updated_variants)
            
            with shopify_lock:
                shopify_success = service.update_shopify_prices(updated_variants)
                local_stats['shopify_synced'] += shopify_success
                
            for variant in updated_variants:
                if variant['change'] > 0:
                    local_stats['price_increases'] += 1
                else:
                    local_stats['price_decreases'] += 1
                    
                if service.is_big_change(variant['old_price'], variant['new_price']):
                    local_stats['big_changes'].append({
                        'name': card['name'], 'number': card['number'], 'condition': variant['condition'],
                        'old_price': variant['old_price'], 'new_price': variant['new_price'],
                        'change': variant['change'], 'change_percent': variant['change_percent']
                    })
            print(f" ✅ Updated {len(updated_variants)} variants")
        else:
            local_stats['no_change'] += 1
            print(f" ⏭️  No change")
        
        time.sleep(0.5)
        
    print(f"\n✅ Thread '{group_name}' completed: {local_stats['total_updated']} cards updated")
    return local_stats

def merge_stats(stats_list):
    merged = {
        'total_processed': 0, 'total_updated': 0, 'variants_updated': 0, 'shopify_synced': 0,
        'price_increases': 0, 'price_decreases': 0, 'failed': 0, 'no_change': 0, 'big_changes': []
    }
    for stats in stats_list:
        for k in merged:
            if isinstance(merged[k], list):
                merged[k].extend(stats[k])
            else:
                merged[k] += stats[k]
    return merged

def main():
    parser = argparse.ArgumentParser(description='Parallel Pricing Engine Job Runner')
    subparsers = parser.add_subparsers(dest='mode', required=True)
    
    # "all" command
    subparsers.add_parser('all', help='Update all cards in database')
    
    # "bucket" command
    bucket_parser = subparsers.add_parser('bucket', help='Update specific price bucket')
    bucket_parser.add_argument('range', choices=['$100+', '$50-100', '$30-50', '$20-30', '$10-20', '<$10'])
    
    # "series" command
    series_parser = subparsers.add_parser('series', help='Update specific set/series')
    series_parser.add_argument('name', help='Exact series name in database (e.g. "Base Set")')
    
    args = parser.parse_args()
    start_time = datetime.now()
    
    print("=" * 100)
    print("💰 PRICING ENGINE JOB - PARALLEL MODE (3 Threads)")
    if args.mode == 'bucket':
        print(f"🎯 PRICE BUCKET: {args.range}")
    elif args.mode == 'series':
        print(f"🎯 SERIES SPECIFIC: {args.name}")
    print("=" * 100)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Threads: {NUM_THREADS}\n")
    
    # Isolate root fetching logic using the pure Service Layer
    service = PricingService()
    series_filter = args.name if args.mode == 'series' else None
    
    print("📚 Step 1: Fetching cards from database...")
    cards = service.fetch_cards_from_database(series_name=series_filter)
    print(f"   ✅ Found {len(cards)} total cards\n")
    
    if args.mode == 'bucket':
        print(f"🗂️  Step 2: Filtering {len(cards)} cards by price bucket {args.range}...")
        
        conn = service.get_db_connection()
        cursor = conn.cursor()
        card_ids = [c['card_id'] for c in cards]
        # Bulk query for bucket prices
        cursor.execute("SELECT p.card_id, v.market_price FROM variants v INNER JOIN products p ON p.id = v.product_id WHERE p.card_id = ANY(%s) AND v.condition = 'NM'", (card_ids,))
        price_lookup = {row[0]: (float(row[1]) if row[1] else 0) for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        
        cards_with_prices = [(c, price_lookup.get(c['card_id'], 0)) for c in cards]
        if args.range == "$100+":
            cards_filtered = [c for c, p in cards_with_prices if p >= 100]
        elif args.range == "$50-100":
            cards_filtered = [c for c, p in cards_with_prices if 50 <= p < 100]
        elif args.range == "$30-50":
            cards_filtered = [c for c, p in cards_with_prices if 30 <= p < 50]
        elif args.range == "$20-30":
            cards_filtered = [c for c, p in cards_with_prices if 20 <= p < 30]
        elif args.range == "$10-20":
            cards_filtered = [c for c, p in cards_with_prices if 10 <= p < 20]
        elif args.range == "<$10":
            cards_filtered = [c for c, p in cards_with_prices if p < 10]
            
        cards = cards_filtered
        print(f"   🎯 Filtered to bucket '{args.range}': {len(cards)} cards\n")
        
    # Split workloads for the thread pool
    if len(cards) == 0:
        print("❌ No items met criteria to execute. Shutting down.")
        sys.exit(0)
        
    chunk_size = max(1, len(cards) // NUM_THREADS)
    chunks = [cards[i:i + chunk_size] for i in range(0, len(cards), chunk_size)]
    while len(chunks) < NUM_THREADS:
        chunks.append([])
    while len(chunks) > NUM_THREADS: # Handle remainder
        chunks[NUM_THREADS-1].extend(chunks.pop())
        
    print(f"   🧵 Thread 1: {len(chunks[0])} cards\n   🧵 Thread 2: {len(chunks[1])} cards\n   🧵 Thread 3: {len(chunks[2])} cards\n")
    print(f"⚡ Step 3: Processing in parallel...\n")
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_1 = executor.submit(process_card_group, chunks[0], "THREAD-1")
        future_2 = executor.submit(process_card_group, chunks[1], "THREAD-2")
        future_3 = executor.submit(process_card_group, chunks[2], "THREAD-3")
        stats = merge_stats([future_1.result(), future_2.result(), future_3.result()])
        
    duration = (datetime.now() - start_time).total_seconds()
    
    print("\n" + "=" * 100 + "\n📊 PRICE UPDATE COMPLETE!\n" + "=" * 100)
    print(f"Cards processed:     {stats['total_processed']}")
    print(f"Cards updated:       {stats['total_updated']}")
    print(f"Variants updated:    {stats['variants_updated']}")
    print(f"Shopify synced:      {stats['shopify_synced']}")
    print(f"Big changes (20%+):  {len(stats['big_changes'])}")
    print(f"\n⏱️  Total time: {duration:.1f} seconds ({duration/60:.1f} minutes)\n" + "=" * 100)
    
    report_data = {
        'date': start_time.strftime('%Y-%m-%d %H:%M:%S'),
        'bucket': args.range if args.mode == 'bucket' else (args.name if args.mode == 'series' else 'ALL'),
        'total_processed': stats['total_processed'], 'total_updated': stats['total_updated'],
        'variants_updated': stats['variants_updated'], 'shopify_synced': stats['shopify_synced'],
        'price_increases': stats['price_increases'], 'price_decreases': stats['price_decreases'],
        'failed': stats['failed'], 'no_change': stats['no_change'],
        'big_changes': sorted(stats['big_changes'], key=lambda x: abs(x['change_percent']), reverse=True),
        'run_time': f"{duration:.1f} seconds"
    }
    PricingReporter.send_email_report(report_data)

if __name__ == "__main__":
    main()
