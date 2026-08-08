# 🏷️ MyTek Promos — Tableau de bord des promotions mytek.tn

Application complète qui extrait **tous les produits en promotion** du site
[mytek.tn](https://www.mytek.tn), calcule le **taux de remise** de chacun et les
affiche sur un **tableau de bord web moderne**, triés de la plus forte remise à
la plus faible.

## 📁 Contenu du projet

```
mytek-promos/
├── scraper.py            # Scraper asynchrone (Python + httpx)
├── index.html            # Tableau de bord web
├── style.css             # Feuille de style (thème sombre)
├── app.js                # Logique JS : chargement, filtres, tri
└── data/
    └── promotions.json   # Cache local généré par le scraper
```

## ⚙️ Prérequis

- **Python 3.10+** avec la librairie `httpx` :

```bash
pip install httpx
```

## 🚀 1. Lancer le scraping

```bash
python3 scraper.py            # scan complet (~10 secondes, 400+ catégories)
python3 scraper.py --limit 5  # scan partiel pour tester
```

Le script :

1. Interroge l'API GraphQL publique de MyTek (moteur OpenSearch) — les pages
   HTML étant protégées par Cloudflare, c'est le canal le plus fiable et le
   plus rapide ;
2. Parcourt **toutes les catégories en parallèle** (concurrence limitée à 8
   requêtes simultanées, retries automatiques) avec gestion de la pagination ;
3. Ne conserve que les produits ayant un **ancien prix** (`price`) et un
   **prix remisé** (`special_price`) ;
4. Calcule `Remise % = (Ancien − Nouveau) / Ancien × 100`, trie par remise
   décroissante et écrit le tout dans `data/promotions.json`.

## 🖥️ 2. Afficher le tableau de bord

Le navigateur bloquant `fetch()` sur les fichiers `file://`, servez le dossier
avec un petit serveur local :

```bash
cd mytek-promos
python3 -m http.server 8000
```

Puis ouvrez **http://localhost:8000** — la page charge le JSON local en
moins d'une seconde (aucun rescraping à l'affichage).

## 🔄 Actualisation des données

Les données sont **mises en cache** dans `data/promotions.json` : la page web ne
rescrape jamais le site. Pour actualiser :

- **Manuellement** : relancer `python3 scraper.py` puis recharger la page ;
- **Automatiquement (cron)** — exemple : tous les jours à 7h :

```cron
0 7 * * * cd /chemin/vers/mytek-promos && /usr/bin/python3 scraper.py >> scraper.log 2>&1
```

## ✨ Fonctionnalités du tableau de bord

- Tri par défaut : **taux de remise décroissant** (badge `-XX %`, animé si ≥ 50 %) ;
- Filtres dynamiques : **recherche textuelle**, **catégorie**, **plage de prix** ;
- Tris additionnels : économies (DT), prix, nom ;
- Par produit : image, titre, catégorie, ancien prix barré, nouveau prix,
  badge de remise, **montant économisé en DT**, lien direct MyTek ;
- Statistiques globales et **date/heure du dernier scan** dans l'en-tête.

## 📝 Notes

- Les prix sont affichés en dinars tunisiens (DT) au format `fr-TN` ;
- Un produit présent dans plusieurs catégories n'apparaît qu'une fois
  (catégories fusionnées) ;
- En cas d'erreur réseau, le scraper réessaie 3 fois avec délai progressif.
