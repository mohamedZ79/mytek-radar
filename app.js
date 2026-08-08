/* ============================================================
   MyTek Promos — Logique du tableau de bord
   Charge data/promotions.json (cache local généré par scraper.py)
   puis gère l'affichage, le tri et les filtres dynamiques.
   ============================================================ */

"use strict";

// ---------- État global ----------
let allProducts = [];   // toutes les promos chargées depuis le JSON
let filtered = [];      // sous-ensemble après filtres

// ---------- Raccourcis DOM ----------
const $ = (id) => document.getElementById(id);
const grid = $("grid");

// ---------- Formatage ----------
/** Formate un prix en dinars tunisiens : 1234.5 → "1 234,500 DT" */
const fmtDT = (n) =>
  n.toLocaleString("fr-TN", { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + " DT";

/** Formate la date du scan en français */
const fmtDate = (iso) =>
  new Date(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });

// ---------- Chargement des données ----------
async function loadData() {
  // Cas 1 : données embarquées dans la page (version autonome pour smartphone)
  if (window.PROMO_DATA) return window.PROMO_DATA;
  // Cas 2 : données lues depuis le fichier JSON (version serveur local)
  // cache-buster (?t=) pour toujours lire la dernière version du JSON
  const res = await fetch("data/promotions.json?t=" + Date.now());
  if (!res.ok) throw new Error("promotions.json introuvable — lancez d'abord python3 scraper.py");
  return res.json();
}

// ---------- Statistiques d'en-tête ----------
function renderStats(data) {
  $("lastScan").textContent = fmtDate(data.scanned_at);
  $("statCount").textContent = data.product_count.toLocaleString("fr-FR");
  const max = Math.max(...allProducts.map((p) => p.discount_pct));
  const avg = allProducts.reduce((s, p) => s + p.discount_pct, 0) / allProducts.length;
  const sav = allProducts.reduce((s, p) => s + p.savings, 0);
  $("statMax").textContent = "-" + max.toFixed(1) + " %";
  $("statAvg").textContent = "-" + avg.toFixed(1) + " %";
  $("statSavings").textContent = fmtDT(sav);
}

// ---------- Liste des catégories ----------
function renderCategories() {
  const cats = new Set();
  allProducts.forEach((p) => p.categories.forEach((c) => cats.add(c)));
  const select = $("categorySelect");
  [...cats].sort((a, b) => a.localeCompare(b, "fr")).forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    select.appendChild(opt);
  });
}

// ---------- Filtrage + tri ----------
function applyFilters() {
  const q = $("searchInput").value.trim().toLowerCase();
  const cat = $("categorySelect").value;
  const min = parseFloat($("priceMin").value) || 0;
  const max = parseFloat($("priceMax").value) || Infinity;

  filtered = allProducts.filter((p) => {
    if (cat && !p.categories.includes(cat)) return false;
    if (p.new_price < min || p.new_price > max) return false;
    if (q && !(p.name + " " + p.brand + " " + p.sku).toLowerCase().includes(q)) return false;
    return true;
  });

  const sorts = {
    discount_desc: (a, b) => b.discount_pct - a.discount_pct,   // défaut : % décroissant
    discount_asc: (a, b) => a.discount_pct - b.discount_pct,
    savings_desc: (a, b) => b.savings - a.savings,
    price_asc: (a, b) => a.new_price - b.new_price,
    price_desc: (a, b) => b.new_price - a.new_price,
    name_asc: (a, b) => a.name.localeCompare(b.name, "fr"),
  };
  filtered.sort(sorts[$("sortSelect").value] || sorts.discount_desc);

  renderGrid();
}

// ---------- Affichage de la grille ----------
function renderGrid() {
  $("emptyMsg").hidden = filtered.length > 0;
  grid.innerHTML = filtered
    .map(
      (p) => `
    <article class="card">
      <div class="card-img-wrap">
        <span class="badge ${p.discount_pct >= 50 ? "hot" : ""}">-${p.discount_pct.toFixed(0)} %</span>
        <img src="${p.image}" alt="${escapeHtml(p.name)}" loading="lazy"
             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><rect width=%22200%22 height=%22200%22 fill=%22%23eee%22/><text x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 fill=%22%23999%22 font-size=%2216%22>Image indisponible</text></svg>'" />
      </div>
      <div class="card-body">
        <span class="card-cat">${escapeHtml(p.categories[0] || "Divers")}</span>
        <h3 class="card-title" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</h3>
        <div class="card-prices">
          <span class="price-old">${fmtDT(p.old_price)}</span>
          <span class="price-new">${fmtDT(p.new_price)}</span>
        </div>
        <span class="card-savings">Vous économisez <strong>${fmtDT(p.savings)}</strong></span>
        <a class="card-link" href="${p.url}" target="_blank" rel="noopener">Voir sur MyTek →</a>
      </div>
    </article>`
    )
    .join("");
}

/** Échappe le HTML pour éviter toute injection via les titres produits */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---------- Événements ----------
["searchInput", "priceMin", "priceMax"].forEach((id) =>
  $(id).addEventListener("input", applyFilters)
);
["categorySelect", "sortSelect"].forEach((id) =>
  $(id).addEventListener("change", applyFilters)
);
$("resetBtn").addEventListener("click", () => {
  $("searchInput").value = "";
  $("categorySelect").value = "";
  $("priceMin").value = "";
  $("priceMax").value = "";
  $("sortSelect").value = "discount_desc";
  applyFilters();
});

// ---------- Démarrage ----------
(async () => {
  try {
    const data = await loadData();
    allProducts = data.products; // déjà triées par % décroissant par le scraper
    renderStats(data);
    renderCategories();
    applyFilters();
  } catch (err) {
    grid.innerHTML = "";
    $("emptyMsg").hidden = false;
    $("emptyMsg").textContent = "⚠ " + err.message;
    $("lastScan").textContent = "aucune donnée";
  }
})();
