/* DataPilot — front-end logic. No framework, no build step. */

/* ── Configuration: edit these values ─────────────────────────────────── */
const CONFIG = {
  // Power BI → File → Embed report → Publish to web (public) → copy the *link*
  // (https://app.powerbi.com/view?r=...). Leave empty to show a placeholder.
  powerbiAtfmUrl: "",
  newsFile: "news.json",
  pageSize: 13,           // lead story + 12
};

/* Annual ATFM delay minutes (billions), read off the dashboard’s yearly chart.
   2026 is year-to-date. Used only for the hero sparkline. */
const ATFM_YEARLY = [
  [2011, .11], [2012, .06], [2013, .05], [2014, .06], [2015, .07], [2016, .09],
  [2017, .095], [2018, .19], [2019, .175], [2020, .02], [2021, .02], [2022, .16],
  [2023, .185], [2024, .22], [2025, .185], [2026, .12],
];

const CATEGORY_ORDER = ["ATM & Airspace", "Airlines", "Airports", "Routes", "Manufacturers", "Safety", "Regulation", "Sustainability", "Industry"];

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── UTC clock ─────────────────────────────────────────────────────────── */
function zulu(d) {
  return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0") + "Z";
}
function tickClock() { $("#utc-clock").textContent = zulu(new Date()); }
tickClock();
setInterval(tickClock, 15000);

/* ── Sparkline ─────────────────────────────────────────────────────────── */
(function drawSpark() {
  const svg = $("#spark-svg");
  if (!svg) return;
  const W = 320, H = 96, padT = 14, padB = 4;
  const max = Math.max(...ATFM_YEARLY.map((d) => d[1]));
  const x = (i) => (i / (ATFM_YEARLY.length - 1)) * W;
  const y = (v) => padT + (1 - v / max) * (H - padT - padB);
  const pts = ATFM_YEARLY.map((d, i) => [x(i), y(d[1])]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = line + ` L${W} ${H} L0 ${H} Z`;
  const iPeak = ATFM_YEARLY.findIndex((d) => d[1] === max);
  const iCovid = ATFM_YEARLY.findIndex((d) => d[0] === 2020);
  svg.innerHTML = `
    <path class="area" d="${area}"/>
    <line class="base" x1="0" y1="${H}" x2="${W}" y2="${H}"/>
    <path class="line" d="${line}"/>
    <circle class="dot" cx="${pts[iPeak][0]}" cy="${pts[iPeak][1]}" r="3.5"/>
    <circle class="dot" cx="${pts[iCovid][0]}" cy="${pts[iCovid][1]}" r="3.5"/>
    <text class="spark-label" x="${pts[iPeak][0]}" y="${pts[iPeak][1] - 7}" text-anchor="middle">2024 peak</text>
    <text class="spark-label" x="${pts[iCovid][0] + 6}" y="${pts[iCovid][1] - 8}" text-anchor="start">COVID-19</text>`;
})();

/* ── Power BI embed ────────────────────────────────────────────────────── */
(function mountEmbed() {
  const box = $("#embed-atfm");
  const url = CONFIG.powerbiAtfmUrl.trim();
  if (url) {
    box.innerHTML = `<iframe title="ATFM Delays — Power BI report" src="${esc(url)}" allowfullscreen loading="lazy"></iframe>`;
    const open = $("#dash-open");
    open.href = url;
    open.hidden = false;
  } else {
    box.innerHTML = `<div class="embed-empty"><strong>Interactive report loading soon</strong>
      <span>The Power BI report will appear here once its public link is added to <code>app.js</code>.</span></div>`;
  }
})();

/* ── News ──────────────────────────────────────────────────────────────── */
const state = { items: [], cat: "All", q: "", shown: CONFIG.pageSize };

function relTime(iso) {
  const t = new Date(iso);
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return mins + " min ago";
  const h = Math.round(mins / 60);
  if (h < 24) return h + " h ago";
  const d = Math.round(h / 24);
  return d === 1 ? "Yesterday" : d + " days ago";
}
function dayLabel(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

function filtered() {
  const q = state.q.toLowerCase();
  return state.items.filter((i) =>
    (state.cat === "All" || i.category === state.cat) &&
    (!q || (i.title + " " + i.summary + " " + i.source).toLowerCase().includes(q)));
}

function renderChips() {
  const counts = {};
  state.items.forEach((i) => (counts[i.category] = (counts[i.category] || 0) + 1));
  const cats = ["All", ...CATEGORY_ORDER.filter((c) => counts[c])];
  $("#chips").innerHTML = cats.map((c) => `
    <button class="chip" role="tab" aria-selected="${c === state.cat}" data-cat="${esc(c)}">
      ${esc(c)}<span class="n">${c === "All" ? state.items.length : counts[c]}</span>
    </button>`).join("");
}

function storyHTML(i, lead) {
  return `<article class="story${lead ? " lead" : ""}">
    <div class="story-time"><b>${esc(dayLabel(i.published))}</b>${esc(zulu(new Date(i.published)))}</div>
    <div>
      <span class="story-cat">${esc(i.category)}</span>
      <h3><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a></h3>
      ${i.summary ? `<p>${esc(i.summary)}</p>` : ""}
      <div class="story-src">${esc(i.source)} · ${esc(relTime(i.published))}${i.lang && i.lang !== "en" ? `<span class="lang">${esc(i.lang.toUpperCase())}</span>` : ""}</div>
    </div>
  </article>`;
}

function renderNews() {
  const list = filtered();
  const box = $("#news");
  if (!list.length) {
    box.innerHTML = `<p class="news-empty">${state.items.length ? "No stories match this filter." : "The briefing is empty right now — check back after the next update."}</p>`;
    $("#more").hidden = true;
    return;
  }
  box.innerHTML = list.slice(0, state.shown).map((i, n) => storyHTML(i, n === 0)).join("");
  $("#more").hidden = list.length <= state.shown;
}

$("#chips").addEventListener("click", (e) => {
  const b = e.target.closest(".chip");
  if (!b) return;
  state.cat = b.dataset.cat;
  state.shown = CONFIG.pageSize;
  renderChips();
  renderNews();
});
let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); state.shown = CONFIG.pageSize; renderNews(); }, 120);
});
$("#more").addEventListener("click", () => { state.shown += 12; renderNews(); });

async function loadNews() {
  try {
    const res = await fetch(CONFIG.newsFile + "?v=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    state.items = (data.items || []).sort((a, b) => b.published.localeCompare(a.published));

    const upd = new Date(data.updated);
    $("#strip-updated").textContent = dayLabel(data.updated) + " " + zulu(upd);
    $("#strip-count").textContent = state.items.length;
    $("#strip-sources").textContent = (data.sources || []).length;
    $("#footer-sources").textContent = (data.sources || []).join(", ") || "—";
    $("#briefing-date").textContent = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

    renderChips();
    renderNews();
  } catch (err) {
    $("#news").innerHTML = `<p class="news-empty">The briefing could not be loaded right now.</p>`;
    console.error("news.json:", err);
  }
}
loadNews();
