# Overnight Session Progress — 2026-05-02

Session: ~02:00–06:00 UTC

---

## ✅ Done

### T1 — fix(nb_no): defensive subjects/creators parsing
**Commit:** `788d53b`

Two bugs fixed in `harvester/search.py` `search_nb()`:

1. **`creators` join error** (`sequence item 0: expected str instance, dict found`): `creators` field from NB.no API can be a list of dicts. Fixed by iterating and extracting `.name` / `.label` per item, same pattern as the existing subjects handler.
2. **`subjects` not-a-list guard**: Added `isinstance(md.get("subjects"), list)` check so non-list values (strings, dicts, None) are safely skipped instead of crashing the join.

---

### T2 — feat(connector): add BSB, SLUB, Manus Online connectors
**Commit:** `0e53694`

Three new connectors added to `harvester/search.py` and registered in `CONNECTORS` dict. `SOURCE_LABELS` in `src/lib/supabase.ts` updated for all three.

**BSB — Bayerische Staatsbibliothek** (`search_bsb`):
- Uses standard SRU catalog endpoint: `https://opacplus.bsb-muenchen.de/TouchPoint/sru/DB=1/`
- Returns XML (Dublin Core schema). Parsed with `xml.etree.ElementTree` (new import added).
- Extracts: title, creator, date, subject, identifier, publisher, language, doc_type.

**SLUB Dresden** (`search_slub`):
- Uses VuFind JSON API: `https://katalog.slub-dresden.de/api/v1/search`
- Extracts: title, author, publishDate, topic/subject, format, language, cover URL, IIIF links.
- Detects digital.slub-dresden.de links for IIIF.

**Manus Online / ICCU** (`search_manus`):
- Tries JSON at `https://manus.iccu.sbn.it/json/ricerca` first.
- Falls back to HTML parsing of `opac_SchedaScheda.php` search results (regex-based).
- Fields: segnatura/titolo, autore, datazione, luogo_conservazione, biblioteca.

⚠️ **Note for Ardi**: Network probing was not possible in the sandbox. Endpoint correctness should be verified on first harvest run (Monday cron). If any API returns 404/403, the connector silently returns `[]` — check `SUPABASE_HARVEST_LOG` after Monday's harvest. SLUB VuFind path may need updating if their API structure differs.

---

### T3 — feat(mapa): period slider + source filter + clustering
**Commit:** `060d46a`

`src/pages/mapa.astro` fully rewritten. `src/lib/supabase.ts` `getMapPoints()` updated.

**Changes:**
1. **`getMapPoints()` now fetches EDH + Wikidata + Pelagios** (was EDH-only). Wikidata `coord_wkt` parsed via WKT regex `Point(lng lat)`. `date_year_min` added to `MapPoint` interface.
2. **Period slider** (dual range, -300 to 2000): filters visible markers by `date_year_min`. Records without date always shown.
3. **Source filter pills** (Sve / EDH / Wikidata / Pelagios) above map — each toggles marker visibility.
4. **Marker clustering** via `leaflet.markercluster@1.5.3` loaded from unpkg. All markers wrapped in `L.markerClusterGroup()`.
5. **Count display**: "Prikazano X od Y find-spotova" updates on every filter change.
6. Color-coded markers: EDH = crimson, Wikidata = blue.

---

### T4 — feat(timeline): vremenska-osa page with century bars
**Commit:** `7f2c0ea`

New file: `src/pages/vremenska-osa.astro`

**Features:**
- SSR: fetches all `date_year_min` values from Supabase at render time (up to 2000 records).
- Groups by century (`Math.floor(year/100)*100`), handles BCE correctly.
- **SVG bar chart**: each century = one bar, height = log-scaled, color by era (BCE/Roman/Medieval/Modern). Each bar is an `<a>` linking to `/?yearMin=X&yearMax=X+99`.
- **Top 5 most-populated centuries** cards, each with 3 sample record links.
- Nav link "Vremenska osa" added to `src/layouts/Layout.astro` (between Mapa and Lokacije).
- `index.astro` updated to read `yearMin`/`yearMax` URL params and pass to `searchResults()` (the function already supported these params, just not the URL layer).

---

### T5 — feat(citation): BibTeX/APA/Chicago export per item
**Commit:** `3ae60ca`

New file: `src/lib/citation.ts` with three export functions:
- `toBibtex(rec)` — `@misc` entry with title, author, year, url, note (source).
- `toApa(rec)` — "Author. (Year). Title. Source. URL"
- `toChicago(rec)` — `Author. "Title." Source. Year. URL.`

`src/pages/item/[id].astro` updated:
- Imports citation functions, generates strings server-side.
- New **"Citiraj" section** inserted before the "Otvori original" button.
- Three toggle buttons (BibTeX / APA / Chicago) — clicking shows the citation text in a `<pre>` block; clicking again collapses.
- **"Kopiraj" button** uses `navigator.clipboard.writeText()`.
- Citation strings passed via `define:vars` to inline script (no API call needed).

---

## ⚠️ Blocked / Notes

None — all tasks completed. T2 connectors have an untested-endpoint caveat (see note above).

---

## ⏭️ Skipped

Nothing skipped.

---

## Notes for Ardi

1. **BSB/SLUB/Manus connectors** were written without live network probing (sandbox restriction). After Monday's cron harvest, check if any returned 0 records. Most likely fix point: SLUB VuFind API path may differ — try `https://www.slub-dresden.de/suche` with different params if `/api/v1/search` returns 404.

2. **Wikidata on map**: The `coord_wkt` parser expects `Point(lng lat)` format (Wikidata SPARQL returns this). If any records used a different WKT variant, they'll be silently skipped. Run `SELECT metadata->>'coord_wkt' FROM archive_results WHERE source='wikidata' LIMIT 5` in Supabase to verify format.

3. **Timeline page** (`/vremenska-osa`) fetches up to 2000 records with `date_year_min`. If total DB grows past 2000 dated records, increase the `.limit()` in the page frontmatter.

4. **Citation section** in `[id].astro`: if `navigator.clipboard` is unavailable (HTTP context or old browser), the copy button will silently fail. Consider adding a fallback (`document.execCommand('copy')`) if this matters.

5. All builds passed `npm run build` cleanly.

---

## Agent #2 (04:30–08:00 UTC)

### ✅ Completed

**A1 — Connectors (+2)**
- **`search_hathitrust`** (fix): replaced empty stub with full Blacklight/Solr implementation. Tries JSON `response.docs` parse first, falls back to HTML title/id regex. Source already in CONNECTORS; added to SOURCE_LABELS.
- **`search_anno`** (new): ÖNB ANNO Austrian newspapers 1700s–1960s. Primary endpoint: SRU XML at `https://anno.onb.ac.at/anno-suche/sru` (Dublin Core). Fallback: `cgi-content/anno-suche?format=json`. Both endpoints 403'd in sandbox — untested live, same caveat as T2. Added to CONNECTORS + SOURCE_LABELS.
- Commit: `69aa110`

**A3 — JSON export endpoint**
- New `/api/export.json` file mirrors `/api/export.csv` exactly (same query params: collection, q, location, source). Returns JSON array with `Content-Disposition` for download.
- "Export JSON" link added to `/zbirke/[slug].astro` next to existing CSV link.
- Commit: `74c9ba9`

**A4 — Advanced search filters**
- `searchResults()` in `supabase.ts`: added `language` (ilike match) and `hasIiif` (not-null `url_iiif`) params. Also fixed latent bug: `if (yearMin)` → `if (yearMin !== undefined)` so year 0 is not skipped.
- `index.astro`: new filter fields — Od/Do godine (year range inputs), Jezik dropdown (7 common languages), "Samo sa IIIF zoom-om" checkbox.
- Commit: `32f3a33`

**A2 — Stats dashboard**
- New `/stats` page with pure CSS/HTML bar charts:
  - Total records + source breakdown (clickable bars → `/?source=X`)
  - Century distribution, log-scaled, era-color-coded (clickable → year range search)
  - Top-10 locations bar chart
  - Coverage gaps section (sources with <30 records)
  - Recent harvest growth (records added last 7 days via `fetched_at`)
- Nav link "Statistika" added after "Vremenska osa" in Layout.astro.
- Commit: `4b98d4e`

**A5 — Bug sweep**
- Verified all 20 source keys in `CONNECTORS` match `SOURCE_LABELS` ✓
- Verified all nav links in `Layout.astro` point to existing page files ✓
- `LOCATIONS` in `supabase.ts` confirmed intentionally wider than `regional-vocab.json` primary_locations (vocab is for query expansion, LOCATIONS is for UI filter) ✓
- `yearMin`/`yearMax` falsy-zero bug fixed in A4 ✓
- Final `npm run build`: clean, no TypeScript errors ✓

---

### ⚠️ Blocked / Notes

- **ANNO SRU** and **HathiTrust Solr**: both 403 in sandbox; untested live. Check SUPABASE_HARVEST_LOG after next cron. If ANNO SRU returns HTTP 403 in production too, try `https://anno.onb.ac.at/anno-suche/#exact=TERM` (SPA URL, no API) — may need scraping approach.

---

### ⏭️ Skipped

Nothing skipped.

---

### Summary

- Total commits this shift: **4** (69aa110, 74c9ba9, 32f3a33, 4b98d4e)
- Time of last commit: **2026-05-02 ~04:38 UTC**
- All tasks A1–A5 complete; A6 (this report) is the final commit.
