"""
CSV Validator Module for Bulk Inventory Upload

Provides validation functions for:
- Set code validation
- Card number range checking
- Fuzzy name matching
- Condition validation
- Cost/quantity validation
- Smart error suggestions
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from difflib import SequenceMatcher
import re


def fuzzy_match(str1, str2, threshold=0.8):
    """
    Calculate similarity between two strings
    Returns True if similarity >= threshold
    """
    similarity = SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
    return similarity >= threshold, similarity


def validate_set_code(set_code, conn):
    """
    Validate if set code exists in database
    Returns: (valid, exists_in_db, suggestion)
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if set exists
        cursor.execute("""
            SELECT DISTINCT set_code 
            FROM cards 
            WHERE set_code = %s
            LIMIT 1
        """, (set_code,))
        
        if cursor.fetchone():
            return True, True, None
        
        # Not found - try to suggest similar sets
        cursor.execute("""
            SELECT DISTINCT set_code 
            FROM cards
        """)
        
        all_sets = [row['set_code'] for row in cursor.fetchall()]
        
        # Find closest match
        best_match = None
        best_similarity = 0
        
        for db_set in all_sets:
            is_match, similarity = fuzzy_match(set_code, db_set, threshold=0.7)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = db_set
        
        if best_match and best_similarity >= 0.7:
            return False, False, best_match
        
        return False, False, None
        
    finally:
        cursor.close()


def validate_card_in_set(set_code, card_number, conn):
    """
    Check if card number exists in set
    Returns: (valid, max_card_number)
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Check if this exact card exists
        cursor.execute("""
            SELECT id FROM cards
            WHERE set_code = %s AND number = %s
            LIMIT 1
        """, (set_code, card_number))
        
        if cursor.fetchone():
            return True, None
        
        # Get max card number in set
        cursor.execute("""
            SELECT MAX(CAST(number AS INTEGER)) as max_num
            FROM cards
            WHERE set_code = %s
            AND number ~ '^[0-9]+$'
        """, (set_code,))
        
        result = cursor.fetchone()
        max_num = result['max_num'] if result else None
        
        return False, max_num
        
    finally:
        cursor.close()


def find_card_by_name_and_set(card_name, set_code, card_number, conn):
    """
    Find card in database by name, set, and number
    Returns: (found, card_id, actual_name, similarity)
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Try exact match first
        cursor.execute("""
            SELECT id, name
            FROM cards
            WHERE set_code = %s AND number = %s
            LIMIT 1
        """, (set_code, card_number))
        
        result = cursor.fetchone()
        
        if result:
            # Check name similarity
            is_match, similarity = fuzzy_match(card_name, result['name'])
            return True, result['id'], result['name'], similarity
        
        # Try by name only (in case number is wrong)
        cursor.execute("""
            SELECT id, name, number
            FROM cards
            WHERE set_code = %s
            AND name ILIKE %s
            LIMIT 5
        """, (set_code, f'%{card_name}%'))
        
        matches = cursor.fetchall()
        
        if matches:
            # Find best match
            best_match = None
            best_similarity = 0
            
            for match in matches:
                is_match, similarity = fuzzy_match(card_name, match['name'])
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = match
            
            if best_match and best_similarity >= 0.8:
                return True, best_match['id'], best_match['name'], best_similarity
        
        return False, None, None, 0
        
    finally:
        cursor.close()


def validate_condition(condition):
    """
    Validate condition code
    Returns: (valid, corrected_value, suggestion)
    """
    valid_conditions = ['NM', 'LP', 'MP', 'HP', 'DMG']
    
    condition_upper = condition.upper().strip()
    
    # Exact match
    if condition_upper in valid_conditions:
        return True, condition_upper, None
    
    # Common variations
    mappings = {
        'NEAR MINT': 'NM',
        'NEARMINT': 'NM',
        'MINT': 'NM',
        'M': 'NM',
        'LIGHTLY PLAYED': 'LP',
        'LIGHTLYPLAYED': 'LP',
        'LIGHT PLAY': 'LP',
        'MODERATELY PLAYED': 'MP',
        'MODERATELYPLAYED': 'MP',
        'MODERATE PLAY': 'MP',
        'HEAVILY PLAYED': 'HP',
        'HEAVILYPLAYED': 'HP',
        'HEAVY PLAY': 'HP',
        'DAMAGED': 'DMG',
        'DAMAGE': 'DMG',
        'D': 'DMG'
    }
    
    if condition_upper in mappings:
        return True, mappings[condition_upper], f"Auto-corrected '{condition}' to '{mappings[condition_upper]}'"
    
    return False, None, f"Invalid condition '{condition}'. Use: NM, LP, MP, HP, or DMG"


def validate_source(source):
    """
    Validate source type
    Returns: (valid, corrected_value, suggestion)
    """
    valid_sources = ['buylist', 'wholesale', 'opening', 'personal', 'trade', 'gift', 'return', 'other']
    
    source_lower = source.lower().strip()
    
    if source_lower in valid_sources:
        return True, source_lower, None
    
    # Common variations
    mappings = {
        'buy': 'buylist',
        'customer': 'buylist',
        'purchase': 'buylist',
        'bulk': 'wholesale',
        'distributor': 'wholesale',
        'supplier': 'wholesale',
        'open': 'opening',
        'pack': 'opening',
        'booster': 'opening',
        'pulled': 'opening',
        'mine': 'personal',
        'collection': 'personal',
        'traded': 'trade',
        'swap': 'trade'
    }
    
    if source_lower in mappings:
        return True, mappings[source_lower], f"Auto-corrected '{source}' to '{mappings[source_lower]}'"
    
    return False, None, f"Invalid source '{source}'. Use: {', '.join(valid_sources)}"


def validate_number(value, field_name, min_value=0):
    """
    Validate numeric field
    Returns: (valid, converted_value, error_message)
    """
    try:
        num = float(value)
        if num <= min_value:
            return False, None, f"{field_name} must be greater than {min_value}"
        return True, num, None
    except (ValueError, TypeError):
        return False, None, f"{field_name} must be a valid number"


def validate_row(row, row_num, conn):
    """
    Validate a single CSV row
    Returns: (valid, warnings, errors, corrections)
    """
    warnings = []
    errors = []
    corrections = {}
    
    required_fields = ['card_name', 'set_code', 'card_number', 'condition', 'quantity', 'unit_cost', 'source']
    
    # Check required fields
    for field in required_fields:
        if field not in row or not str(row[field]).strip():
            errors.append(f"Missing required field: {field}")
            return False, warnings, errors, corrections
    
    card_name = str(row['card_name']).strip()
    set_code = str(row['set_code']).strip()
    card_number = str(row['card_number']).strip()
    condition = str(row['condition']).strip()
    quantity = str(row['quantity']).strip()
    unit_cost = str(row['unit_cost']).strip()
    source = str(row['source']).strip()
    
    # Validate set code
    valid_set, exists_in_db, suggestion = validate_set_code(set_code, conn)
    if not valid_set:
        if suggestion:
            errors.append(f"Set '{set_code}' not found. Did you mean '{suggestion}'?")
        else:
            errors.append(f"Set '{set_code}' not found in database")
    
    # Validate card exists (only if set is valid)
    if valid_set and exists_in_db:
        found, card_id, actual_name, similarity = find_card_by_name_and_set(card_name, set_code, card_number, conn)
        
        if found:
            # Check name similarity
            if similarity < 1.0:
                warnings.append(f"Card name '{card_name}' matched to '{actual_name}' ({similarity*100:.0f}% similar)")
                corrections['card_name'] = actual_name
                corrections['card_id'] = card_id
            else:
                corrections['card_id'] = card_id
        else:
            # Card not in database - will need API fetch
            warnings.append(f"Card '{card_name}' ({set_code}-{card_number}) not in database - will fetch from API")
            corrections['needs_api_fetch'] = True
    
    # Validate condition
    valid_cond, corrected_cond, cond_msg = validate_condition(condition)
    if valid_cond:
        if corrected_cond != condition.upper():
            warnings.append(cond_msg)
        corrections['condition'] = corrected_cond
    else:
        errors.append(cond_msg)
    
    # Validate quantity
    valid_qty, qty_value, qty_error = validate_number(quantity, "Quantity", min_value=0)
    if valid_qty:
        corrections['quantity'] = int(qty_value)
    else:
        errors.append(qty_error)
    
    # Validate unit cost
    valid_cost, cost_value, cost_error = validate_number(unit_cost, "Unit cost", min_value=0)
    if valid_cost:
        corrections['unit_cost'] = cost_value
    else:
        errors.append(cost_error)
    
    # Validate source
    valid_src, corrected_src, src_msg = validate_source(source)
    if valid_src:
        if src_msg:
            warnings.append(src_msg)
        corrections['source'] = corrected_src
    else:
        errors.append(src_msg)
    
    # Store original row data
    corrections['original_row'] = row
    corrections['row_number'] = row_num
    
    is_valid = len(errors) == 0
    
    return is_valid, warnings, errors, corrections


def check_recent_duplicate(card_id, condition, quantity, unit_cost, conn, hours=24):
    """
    Check if this exact card was added recently
    Returns: (is_duplicate, transaction_info)
    """
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                it.id,
                it.quantity,
                it.unit_cost,
                it.created_at,
                c.name,
                c.set_code,
                c.number
            FROM inventory_transactions it
            JOIN variants v ON v.id = it.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN cards c ON c.id = p.card_id
            WHERE c.id = %s
            AND v.condition = %s
            AND it.transaction_type = 'purchase'
            AND it.created_at > NOW() - INTERVAL '%s hours'
            ORDER BY it.created_at DESC
            LIMIT 1
        """, (card_id, condition, hours))
        
        result = cursor.fetchone()
        
        if result:
            return True, result
        
        return False, None
        
    finally:
        cursor.close()
