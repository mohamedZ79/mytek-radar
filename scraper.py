#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scraper.py — Extracteur de promotions MyTek.tn
================================================

Le site mytek.tn est protégé par Cloudflare sur ses pages HTML, mais il expose
une API GraphQL publique (moteur OpenSearch) sur https://www.mytek.tn/graphql.
Ce script l'exploite pour récupérer TOUS les produits, catégorie par catégorie,
de manière asynchrone (httpx + asyncio), puis ne conserve que les produits
en promotion (ancien prix `price` > prix remisé `special_price`).

Étapes :
  1. Récupération de la liste complète des catégories (agrégation `category_ids`).
  2. Parcours asynchrone de chaque catégorie avec pagination (pageSize=100),
     concurrence limitée par un sémaphore pour ne pas surcharger le serveur.
  3. Déduplication des produits (un produit peut appartenir à plusieurs
     catégories) et fusion des noms de catégories.
  4. Calcul de la remise :  remise % = (ancien - nouveau) / ancien * 100
  5. Tri par taux de remise décroissant et écriture dans data/promotions.json
     (utilisé directement par le tableau de bord web).

Usage :
    python3 scraper.py            # scan complet (~1 à 2 minutes)
    python3 scraper.py --limit 20 # scan partiel (20 catégories, pour tester)

Dépendance :  pip install httpx
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GRAPHQL_URL = "https://www.mytek.tn/graphql"
MEDIA_BASE = "https://www.mytek.tn/media/catalog/product"  # base des images Magento
OUTPUT_FILE = Path(__file__).parent / "data" / "promotions.json"

PAGE_SIZE = 100          # produits par page (max accepté par l'API)
MAX_CONCURRENCY = 8      # requêtes simultanées maxi (politesse envers le serveur)
MAX_RETRIES = 3          # tentatives par requête en cas d'erreur réseau
RETRY_DELAY = 2.0        # secondes entre deux tentatives

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Requête GraphQL : liste des catégories (id, nom) via les agrégations
QUERY_CATEGORIES = """
{
  opensearchProductAggregations(search: "") {
    attribute_code
    options { value label count }
  }
}
"""

# Requête GraphQL : produits d'une catégorie, paginés
QUERY_PRODUCTS = """
query ($categoryId: [String], $page: Int, $pageSize: Int) {
  opensearchProductSearch(
    filter: [{key: "category_ids", value: $categoryId}]
    page: $page
    pageSize: $pageSize
  ) {
    total_count
    items {
      id
      sku
      name
      price
      special_price
      final_price
      image
      url
      manufacturer
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Couche réseau
# ---------------------------------------------------------------------------
async def gql(client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict:
    """Exécute une requête GraphQL avec retries et renvoie le champ `data`."""
    payload = {"query": query, "variables": variables or {}}
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.post(GRAPHQL_URL, json=payload, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body and not body.get("data"):
                raise RuntimeError(body["errors"])
            return body["data"]
        except Exception as err:  # réseau, HTTP 5xx, JSON invalide…
            last_err = err
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)  # backoff progressif
    raise RuntimeError(f"Échec après {MAX_RETRIES} tentatives : {last_err}")


async def fetch_categories(client: httpx.AsyncClient) -> list[dict]:
    """Récupère toutes les catégories du site : [{'value': id, 'label': nom}, …]"""
    data = await gql(client, QUERY_CATEGORIES)
    for agg in data["opensearchProductAggregations"]:
        if agg["attribute_code"] == "category_ids":
            return agg["options"]
    return []


async def fetch_category_products(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                                  cat: dict, stats: dict) -> list[dict]:
    """Parcourt toutes les pages d'une catégorie et renvoie ses produits bruts."""
    products, page = [], 1
    async with sem:  # limite le nombre de catégories traitées en parallèle
        while True:
            try:
                data = await gql(client, QUERY_PRODUCTS, {
                    "categoryId": [cat["value"]],
                    "page": page,
                    "pageSize": PAGE_SIZE,
                })
            except RuntimeError as err:
                print(f"  ⚠ catégorie {cat['label']!r} page {page} : {err}", file=sys.stderr)
                stats["errors"] += 1
                break

            result = data["opensearchProductSearch"]
            items = result.get("items") or []
            for item in items:
                item["_category"] = cat["label"].strip()  # mémorise la catégorie
            products.extend(items)

            # Pagination : on s'arrête quand la page est incomplète ou vide
            if len(items) < PAGE_SIZE or page * PAGE_SIZE >= result["total_count"]:
                break
            page += 1

    stats["done"] += 1
    print(f"\r  Catégories scannées : {stats['done']}/{stats['total']}", end="", flush=True)
    return products


# ---------------------------------------------------------------------------
# Traitement des données
# ---------------------------------------------------------------------------
def build_promotions(raw_products: list[dict]) -> list[dict]:
    """Déduplique, filtre les promos et calcule le taux de remise."""
    merged: dict[str, dict] = {}

    for p in raw_products:
        pid = p["id"]
        if pid in merged:
            # Produit déjà vu dans une autre catégorie → fusion des catégories
            merged[pid]["_cats"].add(p["_category"])
            continue
        p["_cats"] = {p["_category"]}
        merged[pid] = p

    promos = []
    for p in merged.values():
        old_price = p.get("price")
        new_price = p.get("special_price") or p.get("final_price")

        # On ne garde QUE les produits avec un ancien prix ET un prix remisé
        if not old_price or not new_price or new_price >= old_price:
            continue

        discount = round((old_price - new_price) / old_price * 100, 1)
        promos.append({
            "id": p["id"],
            "sku": p.get("sku", ""),
            "name": p.get("name", "").strip(),
            "brand": (p.get("manufacturer") or "").strip(),
            "categories": sorted(p["_cats"]),
            "old_price": round(old_price, 3),
            "new_price": round(new_price, 3),
            "discount_pct": discount,
            "savings": round(old_price - new_price, 3),
            "image": MEDIA_BASE + p["image"] if p.get("image") else "",
            "url": p.get("url", ""),
        })

    # Tri par défaut : taux de remise décroissant
    promos.sort(key=lambda x: x["discount_pct"], reverse=True)
    return promos


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------
async def main(limit: int | None = None) -> None:
    start = time.time()
    async with httpx.AsyncClient(headers=HEADERS, http2=False) as client:
        print("① Récupération des catégories…")
        categories = await fetch_categories(client)
        if limit:
            categories = categories[:limit]
        print(f"   → {len(categories)} catégories trouvées.")

        print("② Scan asynchrone des produits…")
        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        stats = {"done": 0, "errors": 0, "total": len(categories)}
        tasks = [fetch_category_products(client, sem, cat, stats) for cat in categories]
        results = await asyncio.gather(*tasks)

    raw = [p for sub in results for p in sub]
    print(f"\n   → {len(raw)} fiches produit récupérées (avec doublons inter-catégories).")

    print("③ Filtrage des promotions et calcul des remises…")
    promos = build_promotions(raw)
    print(f"   → {len(promos)} produits en promotion.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.mytek.tn",
        "product_count": len(promos),
        "duration_seconds": round(time.time() - start, 1),
        "errors": stats["errors"],
        "products": promos,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"④ Écrit : {OUTPUT_FILE}  ({payload['duration_seconds']} s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper des promotions MyTek.tn")
    parser.add_argument("--limit", type=int, default=None,
                        help="Ne scanner que N catégories (test rapide)")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
