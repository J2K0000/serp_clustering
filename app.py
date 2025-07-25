import streamlit as st
import pandas as pd
import requests
import base64
import time
import io
from typing import List, Dict, Set

# --- Classe d'analyse SERP (logique métier) ---
# J'ai gardé votre classe quasi intacte, en modifiant légèrement les retours d'erreur
# pour mieux les afficher dans Streamlit.

class SERPAnalyzer:
    """
    Classe pour interagir avec l'API DataForSEO afin d'analyser les SERP
    et les données de mots-clés.
    """
    def __init__(self, login: str, password: str):
        """Initialise le client avec les identifiants d'API."""
        if not login or not password:
            raise ValueError("Le login et le mot de passe ne peuvent pas être vides.")
        
        credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
        self.serp_url = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
        self.keyword_data_url = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
        self.headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/json'
        }

    def get_search_volumes(self, keywords: List[str]) -> Dict[str, int]:
        """Récupère les volumes de recherche pour une liste de mots-clés."""
        payload = [{"keywords": keywords, "language_code": "fr", "location_code": 2250, "search_partners": False}]
        
        try:
            response = requests.post(self.keyword_data_url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            if 'tasks' in data and data['tasks'][0]['status_code'] == 20000:
                volumes = {}
                for item in data['tasks'][0].get('result', []):
                    if 'keyword' in item and 'search_volume' in item:
                        volumes[item['keyword']] = item.get('search_volume', 0)
                return volumes
            else:
                st.error(f"Erreur API (Volumes de recherche) : {data.get('tasks', [{}])[0].get('status_message', 'Erreur inconnue')}")
                return {}
        except requests.exceptions.RequestException as e:
            st.error(f"Erreur de requête lors de la récupération des volumes : {e}")
            return {}

    def get_serp_urls(self, keyword: str) -> Set[str]:
        """Récupère les URLs des 10 premiers résultats organiques pour un mot-clé."""
        payload = [{"keyword": keyword, "language_code": "fr", "location_code": 2250, "depth": 10}]
        
        try:
            response = requests.post(self.serp_url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()

            if 'tasks' in data and data['tasks'][0]['status_code'] == 20000:
                urls = set()
                items = data['tasks'][0].get('result', [{}])[0].get('items', [])
                for item in items:
                    if item.get('type') == 'organic' and 'url' in item:
                        clean_url = item['url'].split('?')[0].rstrip('/')
                        urls.add(clean_url)
                return urls
            else:
                return set()
        except requests.exceptions.RequestException:
            return set()

    def calculate_url_similarity(self, keywords: List[str], progress_bar) -> pd.DataFrame:
        """Calcule la matrice de similarité d'URL pour une liste de mots-clés."""
        keyword_urls = {}
        total_keywords = len(keywords)
        
        for i, keyword in enumerate(keywords, 1):
            urls = self.get_serp_urls(keyword)
            if urls:
                keyword_urls[keyword] = urls
            time.sleep(0.5)
            progress_bar.progress(i / total_keywords, text=f"Analyse SERP : {keyword} ({i}/{total_keywords})")

        similarity_matrix = []
        for kw1 in keywords:
            row = []
            urls1 = keyword_urls.get(kw1, set())
            for kw2 in keywords:
                urls2 = keyword_urls.get(kw2, set())
                if not urls1 or not urls2:
                    similarity = 0.0
                else:
                    common_urls = len(urls1.intersection(urls2))
                    min_len = min(len(urls1), len(urls2))
                    if min_len == 0:
                        similarity = 0.0
                    else:
                        similarity = (common_urls / min_len) * 100
                row.append(similarity)
            similarity_matrix.append(row)
            
        return pd.DataFrame(similarity_matrix, index=keywords, columns=keywords)

    def suggest_keyword_clusters(self, similarity_df: pd.DataFrame, threshold: float) -> List[List[str]]:
        """Suggère des clusters de mots-clés basés sur un seuil de similarité."""
        clusters = []
        used_keywords = set()
        
        sorted_keywords = similarity_df.sum(axis=1).sort_values(ascending=False).index
        
        for keyword in sorted_keywords:
            if keyword in used_keywords:
                continue
            
            similar_keywords = similarity_df.loc[keyword]
            cluster_candidates = similar_keywords[similar_keywords >= threshold].index.tolist()
            
            new_cluster = []
            for kw in cluster_candidates:
                if kw not in used_keywords:
                    new_cluster.append(kw)
            
            if new_cluster:
                clusters.append(new_cluster)
                for kw in new_cluster:
                    used_keywords.add(kw)
                    
        return clusters

# --- Fonctions utilitaires pour Streamlit ---

def to_excel(similarity_df: pd.DataFrame, clusters: List[List[str]], search_volumes: Dict[str, int]) -> bytes:
    """
    Crée un fichier Excel en mémoire (bytes) contenant la matrice de similarité
    et les clusters de mots-clés.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        similarity_df.round(2).to_excel(writer, sheet_name='Matrice de similarité')
        
        cluster_data = []
        for i, cluster in enumerate(clusters, 1):
            for keyword in cluster:
                cluster_data.append({
                    'Numéro du cluster': i,
                    'Mot-clé': keyword,
                    'Volume de recherche mensuel': search_volumes.get(keyword, 'N/A')
                })
        
        if cluster_data:
            clusters_df = pd.DataFrame(cluster_data)
            clusters_df = clusters_df.sort_values(
                by=['Numéro du cluster', 'Volume de recherche mensuel'],
                ascending=[True, False]
            )
            clusters_df.to_excel(writer, sheet_name='Clusters', index=False)

            workbook = writer.book
            worksheet = writer.sheets['Clusters']
            number_format = workbook.add_format({'num_format': '#,##0'})
            worksheet.set_column('A:A', 18)
            worksheet.set_column('B:B', 40)
            worksheet.set_column('C:C', 25, number_format)

    processed_data = output.getvalue()
    return processed_data

# --- Interface Streamlit ---

st.set_page_config(page_title="Analyseur de Similarité SERP", layout="wide")

st.title("🚀 Analyseur de Similarité SERP")
st.markdown("""
    Cet outil analyse la similarité des pages de résultats de Google (SERP) pour une liste de mots-clés.
    Il vous aide à regrouper les mots-clés qui peuvent être ciblés par une seule et même page (clustering sémantique).
""")

# --- Récupération des identifiants depuis les secrets ---
login = st.secrets.get("DATAFORSEO_LOGIN")
password = st.secrets.get("DATAFORSEO_PASSWORD")

# --- Vérification de la présence des secrets ---
if not login or not password:
    st.error("🔑 ERREUR : Les identifiants DataForSEO ne sont pas configurés.")
    st.info("""
        Veuillez les ajouter dans les "Secrets" de votre application Streamlit.
        Créez un fichier `.streamlit/secrets.toml` dans votre dépôt GitHub avec le contenu suivant :
        ```toml
        DATAFORSEO_LOGIN = "votre_login@email.com"
        DATAFORSEO_PASSWORD = "votre_mot_de_passe_api"
        ```
    """)
    st.stop() # Arrête l'exécution de l'application si les secrets sont manquants

# --- Définition des paramètres ---
st.subheader("1. Définissez vos paramètres")
col1, col2 = st.columns(2)
with col1:
    similarity_threshold = st.slider(
        "Seuil de similarité pour le clustering (%)",
        min_value=0, max_value=100, value=40, step=5,
        help="Pourcentage d'URLs communes nécessaire pour que deux mots-clés soient dans le même cluster."
    )

# --- Saisie des mots-clés ---
st.subheader("2. Collez votre liste de mots-clés")
keywords_input = st.text_area(
    "Un mot-clé par ligne.",
    height=250,
    placeholder="Exemple:\ncréer une application web\ndéveloppement application mobile\nmeilleur framework python"
)

# --- Bouton pour lancer l'analyse ---
if st.button("Lancer l'analyse", type="primary"):
    keywords = [line.strip() for line in keywords_input.split('\n') if line.strip()]

    if not keywords:
        st.warning("Veuillez entrer au moins un mot-clé.")
    else:
        try:
            analyzer = SERPAnalyzer(login=login, password=password)
            
            with st.spinner("Récupération des volumes de recherche..."):
                search_volumes = analyzer.get_search_volumes(keywords)
            
            st.info(f"{len(search_volumes)} volumes de recherche trouvés sur {len(keywords)} mots-clés.")

            progress_bar = st.progress(0, text="Initialisation de l'analyse SERP...")
            
            with st.spinner("Calcul des similarités en cours... Cette étape peut prendre du temps."):
                similarity_df = analyzer.calculate_url_similarity(keywords, progress_bar)
            
            progress_bar.empty()

            st.subheader("📊 3. Résultats de l'analyse")
            
            st.markdown(f"#### Clusters de mots-clés (similarité ≥ {similarity_threshold}%)")
            clusters = analyzer.suggest_keyword_clusters(similarity_df, threshold=similarity_threshold)
            
            if not clusters:
                st.warning("Aucun cluster n'a pu être formé avec le seuil de similarité actuel.")
            else:
                cluster_display_data = []
                for i, cluster in enumerate(clusters, 1):
                    main_keyword = max(cluster, key=lambda kw: search_volumes.get(kw, 0))
                    other_keywords = [kw for kw in cluster if kw != main_keyword]
                    other_keywords.sort(key=lambda kw: search_volumes.get(kw, 0), reverse=True)

                    cluster_display_data.append({
                        "Cluster": f"Cluster {i}",
                        "Mot-clé principal": f"{main_keyword} ({search_volumes.get(main_keyword, 'N/A'):,} SV)",
                        "Mots-clés secondaires": ", ".join([f"{kw} ({search_volumes.get(kw, 'N/A'):,} SV)" for kw in other_keywords])
                    })
                
                clusters_display_df = pd.DataFrame(cluster_display_data)
                st.dataframe(clusters_display_df, use_container_width=True)

            with st.expander("Voir la matrice de similarité détaillée (%)"):
                # Le style .background_gradient nécessite matplotlib
                st.dataframe(similarity_df.style.format("{:.1f}").background_gradient(cmap='Greens', vmin=0, vmax=100))

            st.subheader("📥 4. Télécharger le rapport complet")
            excel_data = to_excel(similarity_df, clusters, search_volumes)
            st.download_button(
                label="Télécharger le fichier Excel",
                data=excel_data,
                file_name=f"rapport_similarite_serp_{time.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except ValueError as e:
            st.error(e)
        except Exception as e:
            st.error(f"Une erreur inattendue est survenue : {e}")
