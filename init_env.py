from getpass import getpass
from pathlib import Path
import textwrap

print("\n--- Airtable credentials (input won’t be shown for API key) ---")
AIRTABLE_API_KEY = getpass("AIRTABLE_API_KEY: ").strip()
BASE_ID = input("BASE_ID (app…): ").strip()
TABLE_ID = input("TABLE_ID (tbl… main collection): ").strip()

print("\n--- Linked table IDs (each starts with tbl…) ---")
STATIONS_TABLE_ID = input("STATIONS_TABLE_ID: ").strip()
LAYOUTS_TABLE_ID = input("LAYOUTS_TABLE_ID: ").strip()
PROP_TYPES_TABLE_ID = input("PROP_TYPES_TABLE_ID: ").strip()
AREAS_TABLE_ID = input("AREAS_TABLE_ID: ").strip()
PRICE_RANGE_TABLE_ID = input("PRICE_RANGE_TABLE_ID: ").strip()
PROPERTY_KIND_TABLE_ID = input("PROPERTY_KIND_TABLE_ID: ").strip()

env_text = f"""AIRTABLE_API_KEY={AIRTABLE_API_KEY}
BASE_ID={BASE_ID}
TABLE_ID={TABLE_ID}

STATIONS_TABLE_ID={STATIONS_TABLE_ID}
LAYOUTS_TABLE_ID={LAYOUTS_TABLE_ID}
PROP_TYPES_TABLE_ID={PROP_TYPES_TABLE_ID}
AREAS_TABLE_ID={AREAS_TABLE_ID}
PRICE_RANGE_TABLE_ID={PRICE_RANGE_TABLE_ID}
PROPERTY_KIND_TABLE_ID={PROPERTY_KIND_TABLE_ID}
"""

Path(".env").write_text(env_text, encoding="utf-8")
print("\n✅ Wrote .env (make sure '.env' is in .gitignore and NOT committed)")

secrets_block = textwrap.dedent(f"""
AIRTABLE_API_KEY = "{AIRTABLE_API_KEY}"
BASE_ID = "{BASE_ID}"
TABLE_ID = "{TABLE_ID}"
STATIONS_TABLE_ID = "{STATIONS_TABLE_ID}"
LAYOUTS_TABLE_ID = "{LAYOUTS_TABLE_ID}"
PROP_TYPES_TABLE_ID = "{PROP_TYPES_TABLE_ID}"
AREAS_TABLE_ID = "{AREAS_TABLE_ID}"
PRICE_RANGE_TABLE_ID = "{PRICE_RANGE_TABLE_ID}"
PROPERTY_KIND_TABLE_ID = "{PROPERTY_KIND_TABLE_ID}"
""")
print("\n🔐 Streamlit → (Your app) → Settings → Secrets — paste this:\n")
print(secrets_block)
