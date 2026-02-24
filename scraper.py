import re
import time
import requests
import pandas as pd
import json

# --- CONFIGURATION ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.e.leclerc/",
}

# Codes catégories simplifiés pour forcer l'accès
CATEGORIES = {
    "bières": "NAVIGATION_bieres",
    "vins-rouges": "NAVIGATION_vins-rouges",
    "vins-blancs": "NAVIGATION_vins-blancs",
    "vins-rosés": "NAVIGATION_vins-roses",
    "spiritueux": "NAVIGATION_spiritueux",
    "champagnes": "NAVIGATION_champagnes",
}

def get_attribute(attributeGroups, code):
    for group in attributeGroups:
        for attr in group.get("attributes", []):
            if attr.get("code") == code: return attr.get("value")
    return None

def extract_abv(value, label):
    if value:
        m = re.search(r'(\d+[\.,]\d*)', str(value))
        if m: return float(m.group(1).replace(',', '.'))
    m = re.search(r'(\d+[\.,]?\d*)\s*[°%]', str(label))
    if m:
        val = float(m.group(1).replace(',', '.'))
        if 1 <= val <= 96: return val
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
        except: pass
    m = re.search(r'(\d+)\s*cl', label, re.IGNORECASE)
    if m: return float(m.group(1)) / 100
    return None

def get_price(item):
    try:
        # Recherche récursive simplifiée
        stack = [item]
        while stack:
            curr = stack.pop()
            if isinstance(curr, dict):
                if "priceWithAllTaxes" in curr: return round(float(curr["priceWithAllTaxes"]) / 100, 2)
                stack.extend(curr.values())
            elif isinstance(curr, list):
                stack.extend(curr)
    except: pass
    return None

def scrape_category(cat_name, cat_code):
    products = []
    page = 1

    while True:
        params = {
            "language": "fr-FR",
            "size": 48,
            "page": page,
            "categories": json.dumps({"code": [cat_code]}),
        }
        try:
            r = requests.get(
                "https://www.e.leclerc/api/rest/live-api/product-search",
                headers=HEADERS,
                params=params,
                timeout=15
            )
            if r.status_code == 403:
                print(f"  🛑 Accès bloqué pour {cat_name}")
                break

            data = r.json()
            items = data.get("items", [])

            if not items:
                break

            for item in items:
                try:
                    nom = item.get("label", "")
                    slug = item.get("slug", "")
                    attr_groups = item.get("attributeGroups", [])
                    prix = get_price(item)
                    volume = extract_volume(attr_groups, nom)
                    abv = extract_abv(get_attribute(attr_groups, "alcool"), nom)
                    image = get_attribute(attr_groups, "image1")
                    image = image.get("url", "") if isinstance(image, dict) else ""
                    url = f"https://www.e.leclerc/pro/{slug}"
                    ratio = None
                    if prix and volume and abv and abv > 0:
                        ratio = round(prix / (volume * abv / 100), 2)
                    products.append({
                        "nom": nom,
                        "categorie": cat_name,
                        "prix_eur": prix,
                        "volume_L": volume,
                        "degre_pct": abv,
                        "ratio": ratio,
                        "image": image,
                        "url": url,
                    })
                except Exception as e:
                    print(f"  ⚠️ Erreur produit : {e}")

            print(f"   ✅ {cat_name} p.{page} : {len(items)} produits trouvés")

            if len(items) < 48:
                break
            page += 1
            time.sleep(1.5)

        except Exception as e:
            print(f"  ❌ Erreur {cat_name} p.{page} : {e}")
            break

    return products

# --- GÉNÉRATEUR WEB ---

def generate_web_view(products):
    products.sort(key=lambda x: x['ratio'] if x['ratio'] is not None else 99999)
    cats = list(set([p['categorie'] for p in products]))
    
    # Boutons de filtres
    filter_html = "".join([f'<button onclick="filterCat(\'{c}\')" class="px-3 py-1 bg-gray-800 border border-gray-700 rounded-md text-xs hover:bg-yellow-600 transition m-1">{c.upper()}</button>' for c in cats])

    # Génération des cartes
    cards_html = ""
    for p in products:
        cards_html += f"""
        <div class="product-card bg-[#1a1f2e] rounded-xl overflow-hidden border border-gray-800 relative group cursor-pointer" 
             data-cat="{p['categorie']}" data-nom="{p['nom'].lower()}" data-ratio="{p['ratio']}" onclick="compare('{p['nom']}', {p['ratio']}, '{p['image']}')">
            <img src="{p['image']}" class="w-full h-32 object-contain bg-white p-2">
            <div class="p-3">
                <div class="text-[9px] text-yellow-500 font-bold uppercase mb-1">{p['categorie']}</div>
                <div class="font-bold text-[11px] h-8 overflow-hidden leading-tight text-gray-200">{p['nom']}</div>
                <div class="mt-2 flex justify-between items-end">
                    <div>
                        <span class="text-lg font-black text-green-400">{p['ratio']}€</span>
                        <div class="text-[7px] text-gray-500 uppercase">/ L Alc. Pur</div>
                    </div>
                    <div class="text-right text-[10px] text-gray-400">
                        <div class="font-bold text-gray-200">{p['prix_eur']}€</div>
                        {p['degre_pct']}% | {p['volume_L']}L
                    </div>
                </div>
            </div>
        </div>"""

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Ethanol Optimizer</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{ background-color: #0d1117; }}
            .no-scrollbar::-webkit-scrollbar {{ display: none; }}
        </style>
    </head>
    <body class="text-gray-300 pb-24">
        <header class="p-4 border-b border-gray-800 sticky top-0 bg-[#0d1117]/90 backdrop-blur-md z-50">
            <h1 class="text-center font-black italic text-xl mb-4 text-white uppercase tracking-widest">Alcool <span class="text-yellow-500">Opti</span></h1>
            <input type="text" id="search" onkeyup="update()" placeholder="Rechercher un alcool..." class="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-sm focus:border-yellow-500 outline-none mb-4">
            <div class="flex overflow-x-auto no-scrollbar pb-2">
                <button onclick="filterCat('all')" class="px-4 py-1 bg-yellow-600 text-black font-bold rounded-md text-xs m-1">TOUT</button>
                {filter_html}
            </div>
        </header>

        <div id="compare-bar" class="fixed bottom-0 left-0 right-0 bg-yellow-600 p-3 text-black font-bold hidden flex justify-between items-center z-[100]">
            <div id="comp-1" class="text-xs truncate max-w-[40%]">Sélectionnez...</div>
            <div class="text-xl italic">VS</div>
            <div id="comp-2" class="text-xs truncate max-w-[40%]">Sélectionnez...</div>
            <button onclick="resetCompare()" class="bg-black text-white px-2 py-1 rounded text-[10px]">X</button>
        </div>

        <main class="p-4">
            <div id="grid" class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {cards_html}
            </div>
        </main>

        <script>
            let selection = [];
            function filterCat(c) {{
                window.currentCat = c;
                update();
            }}
            function update() {{
                let search = document.getElementById('search').value.toLowerCase();
                let cat = window.currentCat || 'all';
                document.querySelectorAll('.product-card').forEach(card => {{
                    let matchSearch = card.dataset.nom.includes(search);
                    let matchCat = (cat === 'all' || card.dataset.cat === cat);
                    card.style.display = (matchSearch && matchCat) ? 'block' : 'none';
                }});
            }}
            function compare(nom, ratio, img) {{
                selection.push({{nom, ratio}});
                document.getElementById('compare-bar').classList.remove('hidden');
                if(selection.length === 1) {{
                    document.getElementById('comp-1').innerText = nom + " (" + ratio + "€)";
                }} else {{
                    document.getElementById('comp-2').innerText = nom + " (" + ratio + "€)";
                    let best = selection[0].ratio < selection[1].ratio ? selection[0].nom : selection[1].nom;
                    setTimeout(() => alert("Le plus rentable est : " + best), 100);
                    selection = [];
                }}
            }}
            function resetCompare() {{
                selection = [];
                document.getElementById('compare-bar').classList.add('hidden');
            }}
        </script>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)
    print("\n✅ Site web prêt : index.html")


# --- MAIN ---
all_products = []
for name, code in CATEGORIES.items():
    print(f"🚀 Scan {name}...")
    all_products.extend(scrape_category(name, code))

# Export JSON et CSV
with open("alcools.json", "w", encoding="utf-8") as f:
    json.dump(all_products, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(all_products)
df.to_csv("alcools.csv", index=False)

print(f"\n✅ {len(all_products)} produits exportés")
print(f"Avec ratio: {df['ratio'].notna().sum()}")

# Générer le site uniquement avec les produits qui ont un ratio
produits_valides = [p for p in all_products if p.get("ratio")]
print(f"Produits affichés sur le site: {len(produits_valides)}")
generate_web_view(produits_valides)



# --- EXECUTION ---

all_data = []
for name, code in CATEGORIES.items():
    print(f"🚀 Scan {name}...")
    all_data.extend(scrape_category(name, code))

if all_data:
    df = pd.DataFrame(all_data)
    df.to_csv("alcools.csv", index=False)
    generate_web_view(all_data)