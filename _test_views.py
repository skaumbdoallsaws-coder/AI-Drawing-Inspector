"""Test the reference-views API endpoint."""
import requests
import json

# Test 1: Valid part number
print("=== Test 1: Valid part number 1008176 ===")
resp = requests.get("http://localhost:8000/api/reference-views/1008176")
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Type: {type(data).__name__}")
    print(f"Keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
    for k, v in (data.items() if isinstance(data, dict) else []):
        if isinstance(v, str):
            print(f"  {k}: string, length={len(v)}, starts_with={v[:30]}...")
        else:
            print(f"  {k}: {type(v).__name__} = {v}")
else:
    print(f"Error: {resp.text}")

# Test 2: Nonexistent part number
print("\n=== Test 2: Nonexistent part number ===")
resp2 = requests.get("http://localhost:8000/api/reference-views/NONEXISTENT")
print(f"Status: {resp2.status_code}")
print(f"Response: {resp2.text[:200]}")

# Test 3: Another valid part number
print("\n=== Test 3: Another valid part 004217 ===")
resp3 = requests.get("http://localhost:8000/api/reference-views/004217")
print(f"Status: {resp3.status_code}")
if resp3.status_code == 200:
    data3 = resp3.json()
    print(f"Keys: {list(data3.keys()) if isinstance(data3, dict) else 'not dict'}")
    for k, v in (data3.items() if isinstance(data3, dict) else []):
        if isinstance(v, str):
            print(f"  {k}: string, length={len(v)}")
        else:
            print(f"  {k}: {type(v).__name__} = {v}")
