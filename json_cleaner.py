"""
JSON Cleaner - Sanitizes data to prevent corruption
"""
import json
import re

def clean_for_json(data):
    """Recursively clean data structure to ensure JSON-safe values"""
    if isinstance(data, dict):
        # Clean dictionary
        cleaned = {}
        for key, value in data.items():
            # Skip None keys or ensure key is string
            if key is None:
                continue
            clean_key = str(key) if not isinstance(key, str) else key
            # Sanitize key
            clean_key = ''.join(c if c.isprintable() else '?' for c in clean_key)
            cleaned[clean_key] = clean_for_json(value)
        return cleaned
    
    elif isinstance(data, list):
        # Clean list
        return [clean_for_json(item) for item in data]
    
    elif isinstance(data, str):
        # Clean string - remove control characters
        cleaned_str = ''.join(c if c.isprintable() or c in '\n\t' else '?' for c in data)
        # Encode to ASCII safely
        cleaned_str = cleaned_str.encode('ascii', errors='replace').decode('ascii')
        # Limit excessive length (prevents JSON serialization issues)
        if len(cleaned_str) > 500:
            cleaned_str = cleaned_str[:500] + "..."
        return cleaned_str
    
    elif isinstance(data, (int, float, bool)):
        # Check for invalid float values
        if isinstance(data, float):
            import math
            if math.isnan(data) or math.isinf(data):
                return None  # Convert NaN/Infinity to None (null in JSON)
        # Valid primitives
        return data
    
    elif data is None:
        # Null is safe in JSON
        return None
    
    else:
        # Unknown type - convert to string safely
        return str(data)


def validate_json(data):
    """Test if data can be serialized and deserialized as JSON"""
    try:
        json_str = json.dumps(data, indent=2)
        json.loads(json_str)
        return True, json_str
    except (TypeError, ValueError) as e:
        return False, str(e)
