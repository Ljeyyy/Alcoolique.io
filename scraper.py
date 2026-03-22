import re
import time
import json
import os
import requests
from collections import Counter

# --- CONFIGURATION ---

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.e.leclerc/",
    "Cookie": "_dd_s=aid=cab10ad7-df12-4450-8982-1ed1afc47a99&rum=0&expire=1771955791208; LOCAL_USER_ID=5c734f0c-3347-4cb8-a688-6570bdd58a10; visitedPages=%5B%5B%22home%22%2Ctrue%5D%5D; selected_pickup=signCode%3D0306_pickupId%3DFR0481A_storeName%3DLE%20CANNET; store_priority=default; store=id%3D1506t101t1_name%3DLE%20CANNET%20ROCHEVILLE_slug%3Dle-cannet-rocheville_urlStore%3Dhttps%3A%2F%2Fwww.e.leclerc%2Fmag%2Fe-leclerc-le-cannet-rocheville_postCode%3D06110_signCode%3D1506; default_pickup=signCode%3D1506"
}

CATEGORIES = {
    # Les classiques
    "bières": "NAVIGATION_bieres",
    "vins-rouges": "NAVIGATION_vins-rouges",
    "vins-blancs": "NAVIGATION_vins-blancs",
    "vins-rosés": "NAVIGATION_vins-roses",
    "champagnes": "NAVIGATION_champagnes",
    
    # Les spiritueux & liqueurs
    "spiritueux": "NAVIGATION_spiritueux",
    "anisés": "NAVIGATION_anises",
    "vodkas": "NAVIGATION_vodkas",
    "gins": "NAVIGATION_gins",
    "tequilas": "NAVIGATION_tequilas",
    "liqueurs": "NAVIGATION_liqueurs",
    
    # L'enfer des Rhums
    "rhums": "NAVIGATION_rhums",
    "rhum-blanc": "NAVIGATION_rhum-blanc",
    "rhum-vieux": "NAVIGATION_rhum-vieux",
    "rhum-arrange": "NAVIGATION_rhum-arrange",
    "rhum-francais": "NAVIGATION_rhum-francais",
    "ron": "NAVIGATION_ron",
    "rum": "NAVIGATION_rum",
    
    # L'enfer des Whiskys (D'après ta capture)
    "whiskys": "NAVIGATION_whiskies", # ou NAVIGATION_whisky selon les magasins
    "whisky-ecossais": "NAVIGATION_whisky-ecossais",
    "single-malt": "NAVIGATION_single-malt",
    "blended": "NAVIGATION_blended",
    "whisky-francais": "NAVIGATION_whisky-francais",
    "whisky-japonais": "NAVIGATION_whisky-japonais",
    "whisky-irlandais": "NAVIGATION_whisky-irlandais",
    "whisky-americain": "NAVIGATION_whisky-americain",
    "bourbon": "NAVIGATION_bourbon"
}

# Moyennes par catégorie (Spiritueux reste à None pour éviter les fausses estimations)
DEFAULT_DEGRE_BY_CAT = {
    'vins-rouges': 13.0,
    'vins-blancs': 12.0,
    'vins-rosés': 12.5,
    'champagnes': 12.5,
    'bières': 5.0,
    'spiritueux': None, 
}

PRICE_KEYS = [
    "priceWithAllTaxes", "price", "salePrice", "unitPrice",
    "pricePerUnit", "basePrice", "regularPrice", "sellingPrice",
    "crossedOutPrice", "finalPrice",
]

# --- FONCTIONS D'EXTRACTION ---

def get_attribute(attributeGroups, code):
    for group in attributeGroups:
        for attr in group.get("attributes", []):
            if attr.get("code") == code:
                return attr.get("value")
    return None

def extract_abv(value, label, cat_name=None):
    """Extrait le degré d'alcool avec des regex sécurisées (gère les entiers et décimales)."""
    val = None
    
    # 1. Tentative depuis l'attribut technique de Leclerc
    if value:
        m = re.search(r'(\d+(?:[\.,]\d+)?)', str(value))
        if m: 
            val = float(m.group(1).replace(',', '.'))
    
    # 2. Tentative depuis le nom du produit si l'attribut était vide ou introuvable
    if not val:
        patterns = [
            r'(\d+(?:[\.,]\d+)?)\s*[°%]\s*(?:vol|alc)?',
            r'(\d+(?:[\.,]\d+)?)\s*vol\b',
            r'(\d+(?:[\.,]\d+)?)\s*alc\b',
            r'(?:degré|degre|alcool|alc)\s*:?\s*(\d+(?:[\.,]?\d+)?)' 
        ]
        for pat in patterns:
            m = re.search(pat, str(label), re.IGNORECASE)
            if m:
                temp_val = float(m.group(1).replace(',', '.'))
                if 1 <= temp_val <= 96:
                    val = temp_val
                    break
                    
    # 🚨 GARDE-FOU ANTI-ABSURDITÉS 🚨
    # Si le script a lu une année (ex: 2024) ou une aberration (> 20%) pour du vin/champagne, on annule.
    if val and cat_name in ["vins-rouges", "vins-blancs", "vins-rosés", "champagnes"]:
        if val > 20.0:
            val = None 
            
    # Si on a une valeur valide, on la retourne
    if val:
        return val
        
    # Sinon, on utilise la moyenne de la catégorie (si elle existe, ex: 12.5% pour le vin)
    if cat_name and cat_name in DEFAULT_DEGRE_BY_CAT:
        return DEFAULT_DEGRE_BY_CAT[cat_name]
        
    return None

def extract_volume(attributeGroups, label):
    """Extrait le volume en litres, gère les packs (ex: 6x25cl)."""
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
            
    patterns = [
        (r'(?:(\d+)\s*[xX*]\s*)?(\d+[\.,]?\d*)\s*(L|cl|ml)\b', None),
    ]
    
    for pat, _ in patterns:
        m = re.search(pat, label, re.IGNORECASE)
        if m:
            multiplicateur = float(m.group(1)) if m.group(1) else 1.0
            val = float(m.group(2).replace(',', '.'))
            unit = m.group(3).lower()
            
            volume_total = val * multiplicateur
            
            if unit == 'l':
                return volume_total if volume_total < 50 else None
            elif unit == 'cl':
                return volume_total / 100
            elif unit == 'ml':
                return volume_total / 1000
                
    return None

def get_price(item):
    """Cherche le prix dans la structure JSON de façon fiable."""
    try:
        variants = item.get("variants", [])
        if variants:
            offers = variants[0].get("offers", [])
            if offers:
                price_obj = offers[0].get("price", {})
                if "price" in price_obj:
                    return float(price_obj["price"])
    except:
        pass

    try:
        stack = [item]
        while stack:
            curr = stack.pop()
            if isinstance(curr, dict):
                for key in PRICE_KEYS:
                    if key in curr and curr[key] is not None:
                        try:
                            val = float(curr[key])
                            if val > 0:
                                if isinstance(curr[key], int) and val >= 100:
                                    return round(val / 100, 2)
                                else:
                                    return round(val, 2)
                        except:
                            pass
                stack.extend(v for v in curr.values() if isinstance(v, (dict, list)))
            elif isinstance(curr, list):
                stack.extend(curr)
    except:
        pass
        
    return None

def compute_ratio(prix, volume, degre):
    if prix and volume and degre and degre > 0:
        return round(prix / (volume * degre / 100), 2)
    return None

# --- LOGIQUE PRINCIPALE ---

def enrich_product(p):
    """Recalcule systématiquement sans aucune estimation hasardeuse (Tolérance Zéro)."""
    changed = False
    nom = p.get("nom", "")
    cat_name = p.get("categorie")
    prix = p.get("prix_eur")

    # 1. Volume
    nouveau_vol = extract_volume([], nom)
    if nouveau_vol and nouveau_vol != p.get("volume_L"):
        p["volume_L"] = nouveau_vol
        changed = True

    # 2. Degré (Protégé par le garde-fou dans extract_abv)
    nouvel_abv = extract_abv(None, nom, cat_name)
    if nouvel_abv and nouvel_abv != p.get("degre_pct"):
        p["degre_pct"] = nouvel_abv
        changed = True

    # 3. Ratio
    if prix and p.get("volume_L") and p.get("degre_pct"):
        nouveau_ratio = compute_ratio(prix, p.get("volume_L"), p.get("degre_pct"))
        if nouveau_ratio != p.get("ratio"):
            p["ratio"] = nouveau_ratio
            p["ratio_estime"] = (p.get("degre_pct") == DEFAULT_DEGRE_BY_CAT.get(cat_name))
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
                if slug in existing_slugs:
                    continue

                nom = item.get("label", "")
                attr_groups = item.get("attributeGroups", [])
                
                prix = get_price(item)
                if prix is None:
                    continue
                    
                volume = extract_volume(attr_groups, nom)
                abv = extract_abv(get_attribute(attr_groups, "alcool"), nom, cat_name)
                image_attr = get_attribute(attr_groups, "image1")
                image = image_attr.get("url", "") if isinstance(image_attr, dict) else ""
                    
                ratio = None
                ratio_estime = False
                
                if prix and volume and abv:
                    ratio = compute_ratio(prix, volume, abv)
                    if ratio:
                        ratio_estime = (abv == DEFAULT_DEGRE_BY_CAT.get(cat_name))

                p = {
                    "nom": nom,
                    "slug": slug,
                    "categorie": cat_name,
                    "prix_eur": prix,
                    "volume_L": volume,
                    "degre_pct": abv,
                    "ratio": ratio,
                    "ratio_estime": ratio_estime,
                    "image": image,
                    "url": f"https://www.e.leclerc/pro/{slug}",
                }
                products.append(p)
                new_count += 1
                
                # 🛑 LA LIGNE ANTI-DOUBLON À AJOUTER ICI 🛑
                existing_slugs.add(slug)

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

# Enrichir les existants et corriger les erreurs
enriched = 0
for p in existing.values():
    if enrich_product(p):
        enriched += 1
print(f"  → {enriched} produits recalculés et corrigés")

# Scraper uniquement les nouveaux
existing_slugs = set(existing.keys())
new_products = []
for name, code in CATEGORIES.items():
    print(f"🚀 Scan {name}...")
    new_products.extend(scrape_category(name, code, existing_slugs))

print(f"\n🆕 {len(new_products)} nouveaux produits trouvés")

# Merge
all_products = list(existing.values()) + new_products

# Nettoyage final : on exclut les produits sans ratio
produits_valides = [p for p in all_products if p.get('ratio') is not None]

print(f"📦 Total avant nettoyage : {len(all_products)} produits")
print(f"🧹 Nettoyage : {len(all_products) - len(produits_valides)} produits invalides ou en rupture ignorés.")

# Export de la base propre
with open("alcools.json", "w", encoding="utf-8") as f:
    json.dump(produits_valides, f, ensure_ascii=False, indent=2)

print(f"\n💾 alcools.json mis à jour avec {len(produits_valides)} produits 100% exploitables !")