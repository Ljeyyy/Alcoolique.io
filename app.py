import streamlit as st
import pandas as pd

# 1. Configuration de la page pour les smartphones
st.set_page_config(page_title="Ma Cave à Alcools", layout="centered")

# 2. Ajout d'un titre principal
st.title("🍷 Mon Application d'Alcools")
st.write("Toutes les données de mon scraper, en direct dans ma poche !")

# 3. Fonction pour charger les données (avec cache pour la rapidité)
@st.cache_data
def charger_donnees():
    try:
        # Pandas lit le JSON et le transforme en tableau automatiquement
        df = pd.read_json("alcools.json")
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement : {e}")
        return pd.DataFrame() # Retourne un tableau vide si le fichier est introuvable

# On charge les données dans une variable
df_alcools = charger_donnees()

# 4. Affichage et interactivité
if not df_alcools.empty:
    
    # Ajout d'une barre de recherche
    recherche = st.text_input("🔍 Rechercher une bouteille :")
    
    # Filtrage des données si l'utilisateur tape quelque chose
    if recherche:
        # On filtre la colonne 'name' (modifie 'name' si ta colonne s'appelle autrement)
        # case=False permet de chercher sans se soucier des majuscules/minuscules
        df_filtre = df_alcools[df_alcools['name'].str.contains(recherche, case=False, na=False)]
    else:
        # Sinon, on garde toutes les données
        df_filtre = df_alcools

    # 5. Affichage du tableau adapté à l'écran
    st.dataframe(df_filtre, use_container_width=True)
    
    # Petit compteur sympa en bas
    st.success(f"✅ {len(df_filtre)} bouteilles affichées")
    
else:
    st.warning("⚠️ Aucune donnée à afficher. Vérifie que le fichier alcools.json est bien dans le même dossier !")