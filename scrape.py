"""
scrape.py — Pull Scinuvo product data straight from the website.

WHY THIS WORKS
Each product lives at a page like https://scinuvo.com/Product/25 , and the
product content (name, price, feature badges, details, specs, usage) is built
into that page's HTML. So we just fetch each page and read those fields. This
scales the same whether you have 6 products or 300 — we simply walk the IDs.

WHAT IT DOES
- Loops over product IDs from START_ID to END_ID.
- Fetches each /Product/{id} page.
- Skips any ID that isn't a real product (no price found).
- Extracts ONLY customer-safe fields. It deliberately SKIPS the reviews.
- Saves everything to scraped_products.json for review.

Setup:
    pip install requests beautifulsoup4

Run:
    python scrape.py
"""

import json
import re
import time
import requests
from bs4 import BeautifulSoup

BASE = "https://scinuvo.com/Product/"
START_ID = 1
END_ID = 60          # raise this later when you have more products
DELAY_SECONDS = 0.5  # be polite to your own server


def scrape_one(product_id):
    """Fetch one product page and extract its fields. Returns a dict or None."""
    url = f"{BASE}{product_id}"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "ScinuvoBot/1.0"})
    except requests.RequestException as e:
        print(f"  id {product_id}: request failed ({e})")
        return None

    if resp.status_code != 200:
        return None

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # --- Name + price come from the reliable addToCart script ---
    m = re.search(
        r"const productID = (\d+);.*?const productName = '(.*?)';.*?const basePrice = ([\d.]+);",
        html, re.S,
    )
    if not m:
        # No product script -> this ID isn't a real product page. Skip.
        return None
    name = m.group(2).strip()
    price = float(m.group(3))

    # --- Feature badges (Fast effect within 15 minutes, etc.) ---
    badges = [s.get_text(strip=True) for s in soup.select(".feature-text")]

    # --- Tab sections: details, specs, usage (we ignore 'reviews' on purpose) ---
    def tab_text(tab_id):
        el = soup.find(id=tab_id)
        if not el:
            return ""
        # collapse whitespace into clean text
        return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()

    details = tab_text("details")
    specs = tab_text("specs")
    usage = tab_text("usage")

    return {
        "id": product_id,
        "url": url,
        "name": name,
        "price_jod": price,
        "badges": badges,
        "details": details,
        "specs": specs,
        "usage": usage,
        # NOTE: reviews are intentionally NOT scraped.
    }


def main():
    products = []
    print(f"Scanning product IDs {START_ID} to {END_ID}...\n")
    for pid in range(START_ID, END_ID + 1):
        data = scrape_one(pid)
        if data:
            print(f"  id {pid}: FOUND -> {data['name'][:50]} ({data['price_jod']} JOD)")
            products.append(data)
        time.sleep(DELAY_SECONDS)

    with open("scraped_products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Scraped {len(products)} products -> scraped_products.json")
    print("Send that file back so we can turn it into the bot's knowledge base.")


if __name__ == "__main__":
    main()
