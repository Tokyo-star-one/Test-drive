# src/suumo_scraper.py
from __future__ import annotations

import os
import re
import json
from typing import Optional, List, Tuple

import requests
from bs4 import BeautifulSoup
from googletrans import Translator
from pyairtable import Table, Api
from dotenv import load_dotenv

# --------------------------------------------------------------------------------------
# Environment & constants
# --------------------------------------------------------------------------------------
load_dotenv()  # local dev; in Streamlit we inject env via st.secrets in streamlit_app.py

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "")
BASE_ID = os.getenv("BASE_ID", "")
TABLE_ID = os.getenv("TABLE_ID", "")

# Linked/master tables (IDs!)
STATIONS_TABLE_ID = os.getenv("STATIONS_TABLE_ID", "")          # Train Stations (Name)
LAYOUTS_TABLE_ID = os.getenv("LAYOUTS_TABLE_ID", "")            # Property Layouts (Name)
PROP_TYPES_TABLE_ID = os.getenv("PROP_TYPES_TABLE_ID", "")      # Property Categories (Apartment, Detached house)
AREAS_TABLE_ID = os.getenv("AREAS_TABLE_ID", "")                # Property Locations (areas / wards) (Name)
PRICE_RANGE_TABLE_ID = os.getenv("PRICE_RANGE_TABLE_ID", "")    # Price ranges (Name)
PROPERTY_KIND_TABLE_ID = os.getenv("PROPERTY_KIND_TABLE_ID", "")# For Rent / For Buy (Name)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Curated station/area aliases to avoid awkward machine translations
STATION_ALIASES = {
    "駒沢大学": "Komazawa-Daigaku",
    "南新宿": "Minami-Shinjuku",
    "代々木": "Yoyogi",
}
AREA_ALIASES = {
    "世田谷": "Setagaya",
    "渋谷": "Shibuya",
    "港": "Minato",
    "新宿": "Shinjuku",
    "目黒": "Meguro",
    "品川": "Shinagawa",
    "中野": "Nakano",
    "杉並": "Suginami",
    "大田": "Ota",
    "中央": "Chuo",
    "千代田": "Chiyoda",
    "文京": "Bunkyo",
    "台東": "Taito",
    "豊島": "Toshima",
    "北": "Kita",
    "荒川": "Arakawa",
    "板橋": "Itabashi",
    "練馬": "Nerima",
    "足立": "Adachi",
    "葛飾": "Katsushika",
    "江戸川": "Edogawa",
}

translator = Translator()

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def safe_translate(text: str, src="ja", dest="en") -> str:
    if not text:
        return text
    try:
        return translator.translate(text, src=src, dest=dest).text
    except Exception:
        return text

def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def normalize_station_en(name_en: str) -> str:
    """Title case, remove trailing 'Station', then replace spaces with hyphens."""
    base = normalize_spaces(name_en).title()
    base = base.replace(" Station", "")
    return base.replace(" ", "-")

def airtable_find_by_name(api: Api, table_id: str, name: str) -> Optional[str]:
    if not name:
        return None
    tbl = api.table(BASE_ID, table_id)
    # Escape single quotes for Airtable formula
    formula = "{Name}='%s'" % name.replace("'", "\\'")
    found = tbl.all(formula=formula)
    return found[0]["id"] if found else None

def airtable_get_or_create_by_name(api: Api, table_id: str, name: str) -> Optional[str]:
    rec_id = airtable_find_by_name(api, table_id, name)
    if rec_id:
        return rec_id
    created = api.table(BASE_ID, table_id).create({"Name": name})
    return created["id"]

def parse_price(text: str) -> str:
    """
    Convert strings like '16.4万円', '10000円' → '164,000' or '10,000' etc.
    Return formatted with commas.
    """
    if not text:
        return "0"
    t = text.replace(",", "")
    if "万" in t:
        m = re.search(r"([\d.]+)", t)
        if not m:
            return "0"
        value = int(float(m.group(1)) * 10000)
        return f"{value:,}"
    # plain 円
    m = re.search(r"([\d]+)", t)
    if m:
        return f"{int(m.group(1)):,}"
    return "0"

def parse_minutes(fragment: str) -> Optional[int]:
    # match 歩3分 / 徒歩12分 etc.
    m = re.search(r"(?:歩|徒歩)\s*(\d+)\s*分", fragment)
    return int(m.group(1)) if m else None

def price_range_label(rent_int: int) -> str:
    """
    Map monthly rent to your price-range labels.
    ex: 360000 -> '¥300~399K'
    """
    # Safety
    if rent_int <= 0:
        return "¥100~199K"  # fallback bucket; adjust to your liking

    k = rent_int // 1000  # thousands (e.g., 360000 -> 360)
    if k < 200:
        return "¥100~199K"
    if 200 <= k <= 299:
        return "¥200~299K"
    if 300 <= k <= 399:
        return "¥300~399K"
    if 400 <= k <= 499:
        return "¥400~499K"
    if 500 <= k <= 599:
        return "¥500~599K"
    if 600 <= k <= 699:
        return "¥600~699K"
    if 700 <= k <= 799:
        return "¥700~799K"
    if 800 <= k <= 899:
        return "¥800~899K"
    if 900 <= k <= 999:
        return "¥900~999K"
    return "¥1M~"

def map_property_category_jp_to_en(jp: str) -> Optional[str]:
    mapping = {
        "マンション": "Apartment",
        "一戸建て": "Detached house",
    }
    return mapping.get((jp or "").strip())

def map_property_kind_from_url(url: str) -> Optional[str]:
    """
    chintai -> For Rent
    ms/chuko or ms/shinchiku -> For Buy
    """
    if "chintai" in url:
        return "For Rent"
    if "/ms/chuko/" in url or "/ms/shinchiku/" in url:
        return "For Buy"
    return None

# --------------------------------------------------------------------------------------
# Airtable-specific helper lookups
# --------------------------------------------------------------------------------------
def get_layout_record_id(api: Api, layout_name_jp: str) -> Optional[str]:
    """
    Link to Layouts table. ワンルーム should link to 'Studio'. Others link as-is (e.g., 1LDK).
    """
    if not layout_name_jp:
        return None
    name = "Studio" if layout_name_jp.strip() == "ワンルーム" else layout_name_jp.strip()
    return airtable_find_by_name(api, LAYOUTS_TABLE_ID, name)

def get_or_create_station_id(api: Api, station_ja_or_en: str) -> Optional[str]:
    """
    Translate station name if JA, normalize to your canonical 'Minami-Shinjuku' style,
    then get/create in Stations table by Name.
    """
    if not station_ja_or_en:
        return None

    # curated alias first
    if station_ja_or_en in STATION_ALIASES:
        norm = STATION_ALIASES[station_ja_or_en]
    else:
        en = safe_translate(station_ja_or_en, src="ja", dest="en")
        norm = normalize_station_en(en)

    # Try exact
    rec = airtable_find_by_name(api, STATIONS_TABLE_ID, norm)
    if rec:
        return rec

    # Also try alt forms (spaces vs hyphens)
    alt = norm.replace("-", " ")
    rec_alt = airtable_find_by_name(api, STATIONS_TABLE_ID, alt)
    if rec_alt:
        return rec_alt

    # Not found -> create normalized
    return airtable_get_or_create_by_name(api, STATIONS_TABLE_ID, norm)

def get_or_create_area_id(api: Api, ward_jp: str) -> Optional[str]:
    """
    Ward area (e.g., 世田谷) → English (Setagaya) with alias mapping, then link/create.
    """
    if not ward_jp:
        return None
    if ward_jp in AREA_ALIASES:
        en = AREA_ALIASES[ward_jp]
    else:
        en = safe_translate(ward_jp, src="ja", dest="en").title()
    return airtable_get_or_create_by_name(api, AREAS_TABLE_ID, en)

def get_property_category_id(api: Api, type_en: str) -> Optional[str]:
    if not type_en:
        return None
    return airtable_find_by_name(api, PROP_TYPES_TABLE_ID, type_en)

def get_property_kind_id(api: Api, kind_en: str) -> Optional[str]:
    if not kind_en:
        return None
    return airtable_find_by_name(api, PROPERTY_KIND_TABLE_ID, kind_en)

def get_price_range_id(api: Api, label: str) -> Optional[str]:
    if not label:
        return None
    return airtable_find_by_name(api, PRICE_RANGE_TABLE_ID, label)

# --------------------------------------------------------------------------------------
# SUUMO parsing helpers
# --------------------------------------------------------------------------------------
def extract_name(soup: BeautifulSoup) -> str:
    tag = soup.select_one("h1.section_h1-header-title")
    ja = tag.get_text(strip=True) if tag else ""
    return safe_translate(ja, src="ja", dest="en") if ja else "N/A"

def extract_rent_and_fee(soup: BeautifulSoup) -> Tuple[str, str]:
    # Rent
    rent_tag = soup.select_one("span.property_view_note-emphasis")
    rent = parse_price(rent_tag.get_text(strip=True)) if rent_tag else "0"

    # Management fee
    mgmt = "0"
    for sp in soup.select("div.property_view_note-info > div.property_view_note-list > span"):
        if "管理費" in sp.get_text() or "共益費" in sp.get_text():
            mgmt = parse_price(sp.get_text(strip=True))
            break
    return rent, mgmt

def extract_layout_and_size(soup: BeautifulSoup) -> Tuple[str, str]:
    layout = "N/A"
    size = "N/A"

    row_l = soup.find("th", string=lambda t: t and "間取り" in t)
    if row_l:
        td = row_l.find_next("td")
        if td:
            layout = td.get_text(strip=True)

    row_s = soup.find("th", string=lambda t: t and "専有面積" in t)
    if row_s:
        td = row_s.find_next("td")
        if td:
            raw = td.get_text(strip=True)
            num = re.sub(r"[^\d.]", "", raw)
            if num:
                size = str(round(float(num)))

    return layout, size

def extract_property_category_jp(soup: BeautifulSoup) -> Optional[str]:
    row = soup.find("th", string=lambda t: t and "建物種別" in t)
    if not row:
        return None
    td = row.find_next("td")
    return td.get_text(strip=True) if td else None

def extract_address_jp(soup: BeautifulSoup) -> Optional[str]:
    for tr in soup.select("table.property_view_table tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and "所在地" in th.get_text(strip=True):
            return td.get_text(strip=True)
    return None

def split_address_to_area_and_street(address_jp: str) -> Tuple[Optional[str], Optional[str]]:
    """
    東京都世田谷区玉堤２ -> ward='世田谷', street='玉堤２'
    Remove '東京都' and the '区' suffix from ward for linking.
    """
    if not address_jp:
        return None, None

    t = address_jp
    t = t.replace("東京都", "", 1)

    m = re.match(r"(?P<ward>.+?)区(?P<rest>.*)", t)
    if not m:
        # fallback: try 市 etc., translate entire thing as street
        return None, address_jp

    ward = m.group("ward").strip()
    rest = m.group("rest").strip()
    # street english:
    street_en = safe_translate(rest, src="ja", dest="en")
    street_en = normalize_spaces(street_en)
    return ward, street_en

def extract_stations_and_minutes(soup: BeautifulSoup) -> List[Tuple[str, Optional[int]]]:
    """
    Return up to two: [(station_ja, minutes), ...]
    Looks in the row where th is '駅徒歩'.
    """
    items: List[Tuple[str, Optional[int]]] = []
    row = soup.find("th", string=lambda t: t and "駅徒歩" in t)
    if not row:
        return items
    td = row.find_next("td")
    if not td:
        return items

    for div in td.select("div.property_view_table-read"):
        raw = div.get_text(strip=True)
        if not raw:
            continue

        # after last '/', then remove '駅'
        if "/" in raw:
            st_part = raw.split("/")[-1]
        else:
            st_part = raw
        st_part = normalize_spaces(st_part)

        minutes = parse_minutes(st_part)
        # remove "駅" and everything from '歩..分' onward
        st_clean = re.sub(r"(?:歩|徒歩)\s*\d+\s*分.*", "", st_part)
        st_clean = st_clean.replace("駅", "").strip()
        if not st_clean:
            continue

        # curated alias first
        if st_clean in STATION_ALIASES:
            station_en = STATION_ALIASES[st_clean]
        else:
            station_en = safe_translate(st_clean, src="ja", dest="en")
            station_en = normalize_station_en(station_en)

        items.append((station_en, minutes))
        if len(items) >= 2:
            break

    return items

def extract_images(soup: BeautifulSoup) -> Tuple[Optional[dict], Optional[dict], List[dict]]:
    """
    From full gallery list: first -> cover, second -> plan, rest -> gallery.
    Return (cover, plan, gallery_list_of_dicts)
    """
    imgs = []
    for img in soup.select("ul#js-view_gallery-list img"):
        src = img.get("data-src") or img.get("src")
        if src and src.startswith("http"):
            imgs.append({"url": src})

    cover = imgs[0] if len(imgs) > 0 else None
    plan = imgs[1] if len(imgs) > 1 else None
    gallery = imgs[2:] if len(imgs) > 2 else []
    return cover, plan, gallery

# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def get_suumo_data(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    api = Api(AIRTABLE_API_KEY)

    # Name
    name = extract_name(soup)

    # Rent / Fee
    rent, mgmt = extract_rent_and_fee(soup)

    # Layout / Size
    layout_jp, size = extract_layout_and_size(soup)
    layout_id = get_layout_record_id(api, layout_jp)

    # Address → area + street
    address_jp = extract_address_jp(soup)
    ward_jp, street_en = split_address_to_area_and_street(address_jp or "")
    area_id = get_or_create_area_id(api, ward_jp) if ward_jp else None

    # Deposit / Key money
    deposit = key_money = "0"
    for sp in soup.select("div.property_view_note-list span"):
        t = sp.get_text(strip=True)
        if "敷金" in t:
            deposit = parse_price(t)
        elif "礼金" in t:
            key_money = parse_price(t)

    # Images
    cover_img, plan_img, gallery_imgs = extract_images(soup)

    # Stations
    stations = extract_stations_and_minutes(soup)  # [(station_en, minutes), ...]
    station_ids: List[Optional[str]] = []
    minutes_list: List[Optional[int]] = []
    for st_en, mins in stations:
        # st_en is already normalized (Minami-Shinjuku, etc)
        # Try to find exact or alt; if missing, create it.
        st_id = airtable_get_or_create_by_name(api, STATIONS_TABLE_ID, st_en)
        station_ids.append(st_id)
        minutes_list.append(mins if isinstance(mins, int) else None)

    # pad to two
    while len(station_ids) < 2:
        station_ids.append(None)
    while len(minutes_list) < 2:
        minutes_list.append(None)

    # Property category (建物種別 → Apartment/Detached house)
    prop_cat_id = None
    jp_kind = extract_property_category_jp(soup)
    en_cat = map_property_category_jp_to_en(jp_kind) if jp_kind else None
    if en_cat:
        prop_cat_id = get_property_category_id(api, en_cat)

    # Property kind (For Rent / For Buy) from URL
    kind = map_property_kind_from_url(url)
    kind_id = get_property_kind_id(api, kind) if kind else None

    # Price range
    try:
        rent_int = int(rent.replace(",", ""))
    except Exception:
        rent_int = 0
    pr_label = price_range_label(rent_int)
    pr_id = get_price_range_id(api, pr_label)

    # Build record payload for preview / upload
    data = {
        "Name": name,
        "Property Price": rent,
        "Property Management Fee": mgmt,
        "Property Layout": [layout_id] if layout_id else [],
        "Property Size": size,
        # Linked area + translated street address
        "Property Locations": [area_id] if area_id else [],
        "Location": street_en or "",
        "Property Deposit": deposit,
        "Property Key Money": key_money,
        # Images
        "Property Cover Image": [cover_img] if cover_img else [],
        "Property Plan Image": [plan_img] if plan_img else [],
        "Property Images": gallery_imgs,
        # Stations (two)
        "Access One: Train Station": [station_ids[0]] if station_ids[0] else [],
        "Access One: Minutes to Walk": minutes_list[0],
        "Access Two: Train Station": [station_ids[1]] if station_ids[1] else [],
        "Access Two: Minutes to Walk": minutes_list[1],
        # Property category (Apartment/Detached house)
        "Property Categories": [prop_cat_id] if prop_cat_id else [],
        # For Rent / For Buy
        "Property Type": [kind_id] if kind_id else [],
        # Price range
        "Property Price Range": [pr_id] if pr_id else [],
    }
    return data

def upload_to_airtable(data: dict) -> None:
    """
    Create a row in your main collection.
    """
    table = Table(AIRTABLE_API_KEY, BASE_ID, TABLE_ID)
    table.create(data)
