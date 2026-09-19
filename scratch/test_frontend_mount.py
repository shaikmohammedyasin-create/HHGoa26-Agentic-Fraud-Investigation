"""Verify static frontend mount in FastAPI."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

print("1. Testing GET / (index.html)...")
r = client.get("/")
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:100]}"
assert "Analyst Command Center" in r.text, "Title not found in HTML"
print("   Success: Root URL serves index.html!")

print("2. Testing GET /css/style.css...")
r = client.get("/css/style.css")
assert r.status_code == 200, f"Expected 200, got {r.status_code}"
assert "--bg-base" in r.text
print("   Success: style.css is served!")

print("3. Testing GET /js/api.js...")
r = client.get("/js/api.js")
assert r.status_code == 200, f"Expected 200, got {r.status_code}"
assert "const API" in r.text
print("   Success: api.js is served!")

print("4. Testing GET /js/graph.js...")
r = client.get("/js/graph.js")
assert r.status_code == 200, f"Expected 200, got {r.status_code}"
assert "class GraphRenderer" in r.text
print("   Success: graph.js is served!")

print("5. Testing GET /js/app.js...")
r = client.get("/js/app.js")
assert r.status_code == 200, f"Expected 200, got {r.status_code}"
assert "document.addEventListener" in r.text
print("   Success: app.js is served!")

print("\nALL STATIC ASSETS MOUNTED AND VERIFIED SUCCESSFULLY!")
