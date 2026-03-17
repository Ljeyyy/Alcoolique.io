import re
import time
import json
import os
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.e.leclerc/",
}

CATEGORIES = {
    "bières": "NAVIGATION_bieres",
    "vins-rouges": "NAVIGATION_vins-rouges",
    "vins-blancs": "NAVIGATION_vins-blancs",
    "vins-rosés": "NAVIGATION_vins-roses",
    "spiritueux": "NAVIGATION_spiritueux",
    "champagnes": "NAVIGATION_champagnes",
}

DEFAULT_DEGRE = {
    'anisé': 45, 'vodka': 40, 'gin': 40, 'tequila': 38,
    'rhum': 40, 'whisky': 40, 'cognac': 40, 'liqueur': 20,
}

def get_attribute(attributeGroups, code):
    for group in attributeGroups:
        for attr in group.get("attributes", []):
            if attr.get("code") == code:
                return attr.get("value")
    return None

def extract_abv(value, label):
    # 1. Depuis l'attribut dédié
    if value:
        m = re.search(r'(\d+[\.,]\d*)', str(value))
        if m:
            return float(m.group(1).replace(',', '.'))
    # 2. Depuis le nom : "40% vol", "8,5°", "12.5 % vol"
    patterns = [
        r'(\d+[\.,]\d*)\s*[°%]\s*vol',
        r'(\d+[\.,]\d*)\s*%',
        r'(\d+[\.,]\d*)\s*°',
        r'(\d+[\.,]\d*)\s*vol',
    ]
    for pat in patterns:
        m = re.search(pat, str(label), re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if 1 <= val <= 96:
                return val
    return None

def extract_volume(attributeGroups, label):
    contenu = get_attribute(attributeGroups, "contenu_net")
    unite = get_attribute(attributeGroups, "unite_contenu_net")
    if contenu:
        try:
            val = float(str(contenu).replace(',', '.'))
            unite_label = unite.get("label", "cl") if isinstance(unite, dict) else "cl"
            if unite_label.lower() == "l": return val
            if unite_label.lower() == "cl": return val / 100
        except:
            pass
    # Fallback depuis le nom
    patterns = [
        (r'(\d+[\.,]?\d*)\s*L\b', 'L'),
        (r'(\d+)\s*cl\b', 'cl'),
        (r'(\d+)\s*ml\b', 'ml'),
    ]
    for pat, unit in patterns:
        m = re.search(pat, label, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(',', '.'))
            if unit == 'L' and val < 20: return val
            if unit == 'cl': return val / 100
            if unit == 'ml': return val / 1000
    return None

def get_price(item):
    try:
        stack = [item]
        while stack:
            curr = stack.pop()
            if isinstance(curr, dict):
                if "priceWithAllTaxes" in curr:
                    return round(float(curr["priceWithAllTaxes"]) / 100, 2)
                stack.extend(curr.values())
            elif isinstance(curr, list):
                stack.extend(curr)
    except:
        pass
    return None

def guess_degre_from_name(nom):
    """Devine le degré depuis le nom si tout le reste échoue"""
    n = nom.lower()
    for keyword, degre in DEFAULT_DEGRE.items():
        if keyword in n:
            return degre
    return None

def compute_ratio(prix, volume, degre):
    if prix and volume and degre and degre > 0:
        return round(prix / (volume * degre / 100), 2)
    return None

def enrich_product(p):
    """Tente de remplir les champs manquants depuis le nom"""
    changed = False
    if not p.get("degre_pct"):
        abv = extract_abv(None, p["nom"])
        if not abv:
            abv = guess_degre_from_name(p["nom"])
        if abv:
            p["degre_pct"] = abv
            changed = True
    if not p.get("volume_L"):
        vol = extract_volume([], p["nom"])
        if vol:
            p["volume_L"] = vol
            changed = True
    if not p.get("ratio"):
        r = compute_ratio(p.get("prix_eur"), p.get("volume_L"), p.get("degre_pct"))
        if r:
            p["ratio"] = r
            p["ratio_estime"] = True
            changed = True
    return changed

def scrape_category(cat_name, cat_code, existing_slugs):
    products = []
    page = 1
    new_count = 0

    while True:
        params = {
            "language": "fr-FR",
            "size": 48,
            "page": page,
            "categories": json.dumps({"code": [cat_code]}),
        }
        retries = 0
        while retries < 3:
            try:
                r = requests.get(
                    "https://www.e.leclerc/api/rest/live-api/product-search",
                    headers=HEADERS,
                    params=params,
                    timeout=15
                )
                if r.status_code == 403:
                    print(f"  🛑 Bloqué pour {cat_name}")
                    return products
                if r.status_code == 429:
                    wait = 30 * (retries + 1)
                    print(f"  ⏳ Rate limit, attente {wait}s...")
                    time.sleep(wait)
                    retries += 1
                    continue
                break
            except Exception as e:
                print(f"  ❌ Erreur réseau : {e}, retry {retries+1}/3")
                time.sleep(10)
                retries += 1

        if retries == 3:
            print(f"  ❌ Abandon après 3 retries sur {cat_name} p.{page}")
            break

        data = r.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            try:
                slug = item.get("slug", "")
                # Skip si déjà connu
                if slug in existing_slugs:
                    continue

                nom = item.get("label", "")
                attr_groups = item.get("attributeGroups", [])
                prix = get_price(item)
                volume = extract_volume(attr_groups, nom)
                abv = extract_abv(get_attribute(attr_groups, "alcool"), nom)
                image_attr = get_attribute(attr_groups, "image1")
                image = image_attr.get("url", "") if isinstance(image_attr, dict) else ""

                if not abv:
                    abv = guess_degre_from_name(nom)

                ratio = compute_ratio(prix, volume, abv)

                p = {
                    "nom": nom,
                    "slug": slug,
                    "categorie": cat_name,
                    "prix_eur": prix,
                    "volume_L": volume,
                    "degre_pct": abv,
                    "ratio": ratio,
                    "ratio_estime": ratio is not None and abv == guess_degre_from_name(nom),
                    "image": image,
                    "url": f"https://www.e.leclerc/pro/{slug}",
                }
                products.append(p)
                new_count += 1

            except Exception as e:
                print(f"  ⚠️ Erreur produit : {e}")

        print(f"  ✅ {cat_name} p.{page} : {len(items)} vus, {new_count} nouveaux")

        if len(items) < 48:
            break
        page += 1
        time.sleep(1.5)

    return products


# --- MAIN ---
print("📂 Chargement de l'existant...")
existing = {}
if os.path.exists("alcools.json"):
    with open("alcools.json", encoding="utf-8") as f:
        for p in json.load(f):
            if p.get("slug"):
                existing[p["slug"]] = p

print(f"  → {len(existing)} produits déjà en base")

# Enrichir les existants sans ratio
enriched = 0
for p in existing.values():
    if enrich_product(p):
        enriched += 1
print(f"  → {enriched} produits enrichis avec données manquantes")

# Scraper uniquement les nouveaux
existing_slugs = set(existing.keys())
new_products = []
for name, code in CATEGORIES.items():
    print(f"🚀 Scan {name}...")
    new_products.extend(scrape_category(name, code, existing_slugs))

print(f"\n🆕 {len(new_products)} nouveaux produits trouvés")

# Merge
all_products = list(existing.values()) + new_products
print(f"📦 Total : {len(all_products)} produits")
print(f"✅ Avec ratio : {sum(1 for p in all_products if p.get('ratio'))}")

# Export
with open("alcools.json", "w", encoding="utf-8") as f:
    json.dump(all_products, f, ensure_ascii=False, indent=2)

print("💾 alcools.json mis à jour")
