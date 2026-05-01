#!/usr/bin/env python3
"""
archive-search — federated search across European/Italian/Vatican historical archives.

Queries Europeana, Heidelberg Epigraphic Database, Epigraphic Database Roma,
DigiVatLib (IIIF), Internet Archive, and Antenati portal in parallel.
Normalizes results into a common schema and writes JSONL + markdown report.

Usage:
  python3 search.py "Olcinium"
  python3 search.py "Dulcigno" --source europeana --limit 50
  python3 search.py --location ulcinj --years 1400-1700
  python3 search.py --harvest                # Run initial harvest for full vocab
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode

import aiohttp

SKILL_DIR = Path(__file__).parent
VOCAB_PATH = SKILL_DIR / "regional-vocab.json"
STAGING_DIR = Path.home() / ".claude" / "staging" / "archive-search"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

import os

EUROPEANA_KEY = os.environ.get("EUROPEANA_KEY", "apidemo")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://frsgzfzvdxswqjpdmcsd.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
TIMEOUT = aiohttp.ClientTimeout(total=30)
USER_AGENT = "Ulcinno-Archive-Search/1.0 (+https://arhiva.ulcinno.me; ardi.mavric@gmail.com)"


# ---------- normalized record ----------

@dataclass
class Record:
    source: str
    source_id: str
    title: str
    url_original: str
    snippet: str = ""
    author: str = ""
    date_text: str = ""
    date_year_min: int | None = None
    date_year_max: int | None = None
    location: str = ""
    language: str = ""
    doc_type: str = ""
    url_iiif: str = ""
    thumbnail_url: str = ""
    full_text: str = ""
    tags: list[str] = field(default_factory=list)
    relevance: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- vocab loader ----------

def load_vocab() -> dict:
    return json.loads(VOCAB_PATH.read_text())


def expand_location_query(loc_key: str, vocab: dict) -> list[str]:
    """Given a location key like 'ulcinj', return all known name variants."""
    for bucket in ("primary_locations", "regional_locations", "regions"):
        entry = vocab.get(bucket, {}).get(loc_key)
        if entry:
            return list(set(entry.get("modern", []) + entry.get("historical", [])))
    return [loc_key]


def all_search_terms(vocab: dict, include_thematic: bool = False) -> list[tuple[str, str]]:
    """Return list of (location_key, name_variant) tuples for full-vocab harvest."""
    terms = []
    for bucket in ("primary_locations", "regional_locations", "regions"):
        for key, entry in vocab.get(bucket, {}).items():
            if entry.get("priority") == "secondary" and not include_thematic:
                # still include but mark
                pass
            for name in entry.get("modern", []) + entry.get("historical", []):
                terms.append((key, name))
    return terms


# ---------- date parsing ----------

YEAR_RE = re.compile(r"\b(1[0-9]{3}|[1-9][0-9]{2}|[1-9])\b")
ROMAN_TO_INT = {"M": 1000, "CM": 900, "D": 500, "CD": 400, "C": 100, "XC": 90,
                "L": 50, "XL": 40, "X": 10, "IX": 9, "V": 5, "IV": 4, "I": 1}


def parse_year_range(s: str) -> tuple[int | None, int | None]:
    if not s:
        return None, None
    s = str(s)
    yrs = [int(y) for y in YEAR_RE.findall(s)[:4]]
    yrs = [y for y in yrs if 1 <= y <= 2100]
    if not yrs:
        return None, None
    if len(yrs) == 1:
        return yrs[0], yrs[0]
    return min(yrs), max(yrs)


# ---------- HTTP helpers ----------

async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict | None = None) -> dict | None:
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as r:
            if r.status >= 400:
                return None
            return await r.json(content_type=None)
    except Exception as e:
        print(f"  ! fetch_json error {url}: {e}", file=sys.stderr)
        return None


async def fetch_text(session: aiohttp.ClientSession, url: str, params: dict | None = None) -> str | None:
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as r:
            if r.status >= 400:
                return None
            return await r.text()
    except Exception as e:
        print(f"  ! fetch_text error {url}: {e}", file=sys.stderr)
        return None


# ---------- connector: Europeana ----------

async def search_europeana(session, query: str, limit: int = 30) -> list[Record]:
    """https://api.europeana.eu/record/v2/search.json"""
    url = "https://api.europeana.eu/record/v2/search.json"
    params = {
        "wskey": EUROPEANA_KEY,
        "query": query,
        "rows": limit,
        "profile": "rich",
    }
    data = await fetch_json(session, url, params)
    if not data or not data.get("success"):
        return []
    out = []
    for item in data.get("items", []):
        title = " / ".join(item.get("title") or []) or "[no title]"
        creator = " / ".join(item.get("dcCreator") or [])
        date_raw = " / ".join(item.get("year") or []) or " / ".join(item.get("dcDate") or [])
        ymin, ymax = parse_year_range(date_raw)
        url_orig = (item.get("guid") or "").split("?")[0] or item.get("link", "")
        thumb = item.get("edmPreview", [None])[0] if item.get("edmPreview") else ""
        descs = item.get("dcDescription") or []
        snippet = (descs[0][:400] if descs else "")[:400]
        # Derive IIIF manifest URL from Europeana record ID — pattern: /presentation{id}/manifest
        # Most rich-media items expose IIIF via this endpoint.
        rec_id = item.get("id", "")
        iiif_url = f"https://iiif.europeana.eu/presentation{rec_id}/manifest" if rec_id else ""
        rec = Record(
            source="europeana",
            source_id=rec_id,
            title=title[:300],
            author=creator[:200],
            date_text=date_raw,
            date_year_min=ymin,
            date_year_max=ymax,
            url_original=url_orig,
            url_iiif=iiif_url,
            thumbnail_url=thumb or "",
            snippet=snippet,
            doc_type=(item.get("type") or "").lower(),
            language=(item.get("language") or [""])[0] if item.get("language") else "",
            metadata={"data_provider": (item.get("dataProvider") or [None])[0],
                      "rights": (item.get("rights") or [None])[0]},
        )
        out.append(rec)
    return out


# ---------- connector: Heidelberg Epigraphic Database (EDH) ----------

_EDH_GEO_CACHE: list[dict] | None = None

def _load_edh_geo() -> list[dict]:
    """Load EDH geographic dump (one-time, cached). 19MB GeoJSON of ~30k findspots."""
    global _EDH_GEO_CACHE
    if _EDH_GEO_CACHE is not None:
        return _EDH_GEO_CACHE
    path = SKILL_DIR / "data" / "edh-geo.json"
    if not path.exists():
        _EDH_GEO_CACHE = []
        return _EDH_GEO_CACHE
    try:
        data = json.loads(path.read_text())
        _EDH_GEO_CACHE = data.get("features", [])
    except Exception as e:
        print(f"  ! EDH dump load error: {e}", file=sys.stderr)
        _EDH_GEO_CACHE = []
    return _EDH_GEO_CACHE


async def search_edh(session, query: str, limit: int = 50) -> list[Record]:
    """Local EDH geographic dump search. Returns ancient findspots matching query.
    Live API (edh.ub.uni-heidelberg.de) is behind Anubis bot-protection — using daily-mirrored
    GitHub dump (epigraphic-database-heidelberg/data/geography/edhGeographicData.json) instead.
    """
    feats = _load_edh_geo()
    if not feats:
        return []
    # Extract individual terms from quoted OR-list
    terms = [t.strip().strip('"').lower() for t in re.split(r'\s+OR\s+', query) if t.strip()]
    out = []
    for f in feats:
        p = f.get("properties", {})
        name = (p.get("ancient_findspot") or "").strip()
        if not name:
            continue
        nm_lower = name.lower()
        if any(t in nm_lower or nm_lower.startswith(t) for t in terms):
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            edh_uri = p.get("uri", "")
            edh_id = edh_uri.rstrip("/").split("/")[-1] if edh_uri else ""
            rec = Record(
                source="edh",
                source_id=edh_id,
                title=f"Findspot: {name}",
                url_original=edh_uri,
                location=name,
                doc_type="findspot",
                language="latin",
                metadata={
                    "pleiades_uri": p.get("pleiades_uri"),
                    "trismegistos_uri": p.get("trismegistos_geo_uri"),
                    "longitude": coords[0] if coords else None,
                    "latitude": coords[1] if coords else None,
                    "note": "Click EDH URL for inscriptions list at this findspot",
                },
            )
            out.append(rec)
            if len(out) >= limit:
                break
    return out


# ---------- connector: Epigraphic Database Roma (EDR) ----------

async def search_edr(session, query: str, limit: int = 30) -> list[Record]:
    """EDR has no public JSON API, uses HTML search. Skip for now, mark TODO."""
    # TODO: implement HTML scrape of http://www.edr-edr.it/edr_programmi/res_complex_comune.php
    return []


# ---------- connector: Internet Archive ----------

async def search_internet_archive(session, query: str, limit: int = 30) -> list[Record]:
    """https://archive.org/advancedsearch.php"""
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q": query,
        "fl[]": "identifier,title,creator,date,year,description,language,mediatype,subject",
        "rows": limit,
        "output": "json",
    }
    data = await fetch_json(session, url, params)
    if not data:
        return []
    docs = data.get("response", {}).get("docs", [])
    out = []
    for item in docs:
        title = item.get("title", "")
        if isinstance(title, list):
            title = title[0] if title else ""
        ident = item.get("identifier", "")
        date = item.get("date") or str(item.get("year") or "")
        ymin, ymax = parse_year_range(date)
        creator = item.get("creator", "")
        if isinstance(creator, list):
            creator = ", ".join(creator[:3])
        desc = item.get("description", "")
        if isinstance(desc, list):
            desc = " ".join(desc)
        rec = Record(
            source="internet_archive",
            source_id=ident,
            title=title[:300],
            author=creator[:200],
            date_text=str(date),
            date_year_min=ymin,
            date_year_max=ymax,
            url_original=f"https://archive.org/details/{ident}",
            snippet=desc[:400] if desc else "",
            doc_type=item.get("mediatype", ""),
            language=(item.get("language") or [""])[0] if isinstance(item.get("language"), list) else (item.get("language") or ""),
            tags=item.get("subject", []) if isinstance(item.get("subject"), list) else [],
        )
        out.append(rec)
    return out


# ---------- connector: DigiVatLib (Vatican Library, IIIF) ----------

async def search_digivatlib(session, query: str, limit: int = 30) -> list[Record]:
    """DigiVatLib search — HTML search at https://digi.vatlib.it/search?k_q=..."""
    url = "https://digi.vatlib.it/search"
    params = {"k_q": query, "k_n": limit}
    html = await fetch_text(session, url, params)
    if not html:
        return []
    # Simple regex parse — DigiVatLib is server-rendered
    out = []
    # Each hit: <a href="/view/MSS_..." ...>Title</a>
    pattern = re.compile(r'<a[^>]*href="(/(?:view|mss)/([^"]+))"[^>]*>([^<]+)</a>', re.I)
    seen = set()
    for m in pattern.finditer(html):
        path, ident, title = m.group(1), m.group(2), m.group(3).strip()
        if not title or ident in seen:
            continue
        seen.add(ident)
        rec = Record(
            source="digivatlib",
            source_id=ident,
            title=title[:300],
            url_original=f"https://digi.vatlib.it{path}",
            url_iiif=f"https://digi.vatlib.it/iiif/{ident}/manifest.json",
            doc_type="manuscript",
            language="latin",
        )
        out.append(rec)
        if len(out) >= limit:
            break
    return out


# ---------- connector: Pelagios Pleiades (ancient places) ----------

async def search_pelagios(session, query: str, limit: int = 30) -> list[Record]:
    """Pleiades RSS search returns matching ancient places. Enriches with JSON per-place data."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()]
    out: list[Record] = []
    for term in terms[:6]:  # cap to avoid too many requests
        url = "https://pleiades.stoa.org/search_rss"
        params = {"SearchableText": term, "portal_type": "Place"}
        text = await fetch_text(session, url, params)
        if not text:
            continue
        # Parse RSS items: <item><title>...</title><link>...</link><description>...</description>
        items = re.findall(r'<item[^>]*>(.*?)</item>', text, re.S)
        for it in items[:limit // max(len(terms), 1) + 1]:
            title_m = re.search(r'<title[^>]*>(.*?)</title>', it, re.S)
            link_m = re.search(r'<link[^>]*>(.*?)</link>', it, re.S)
            desc_m = re.search(r'<description[^>]*>(.*?)</description>', it, re.S)
            if not link_m:
                continue
            link = link_m.group(1).strip()
            place_id = link.rstrip('/').split('/')[-1]
            title = (title_m.group(1).strip() if title_m else "[no title]").replace('<![CDATA[','').replace(']]>','')
            desc = (desc_m.group(1).strip() if desc_m else "").replace('<![CDATA[','').replace(']]>','')
            rec = Record(
                source="pelagios",
                source_id=place_id,
                title=title[:300],
                url_original=link,
                snippet=desc[:400],
                doc_type="ancient_place",
                language="en",
                metadata={"pleiades_id": place_id, "matched_term": term},
            )
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


# ---------- connector: Wikidata SPARQL ----------

async def search_wikidata(session, query: str, limit: int = 20) -> list[Record]:
    """Wikidata SPARQL — finds places, archaeological sites, historical buildings matching label."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:8]
    if not terms:
        return []
    # Build VALUES clause for label matching across multiple terms
    values = " ".join(f'"{t}"@en "{t}"@la "{t}"@it "{t}"@sh "{t}"@sq' for t in terms)
    sparql = f"""
SELECT DISTINCT ?item ?itemLabel ?desc ?coord ?inception ?country WHERE {{
  VALUES ?label {{ {values} }}
  ?item rdfs:label ?label .
  ?item wdt:P31/wdt:P279* ?type .
  VALUES ?type {{ wd:Q839954 wd:Q486972 wd:Q4022 wd:Q23413 wd:Q570116 wd:Q2065736 wd:Q15324 wd:Q1078765 }}
  OPTIONAL {{ ?item wdt:P625 ?coord }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P17 ?country }}
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,sh,it,la,sq" }}
}}
LIMIT {limit}
"""
    url = "https://query.wikidata.org/sparql"
    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": USER_AGENT,
    }
    try:
        async with session.get(url, params={"query": sparql}, headers=headers) as r:
            if r.status >= 400:
                return []
            data = await r.json(content_type=None)
    except Exception as e:
        print(f"  ! wikidata error: {e}", file=sys.stderr)
        return []
    out = []
    for b in data.get("results", {}).get("bindings", []):
        qid = b.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        label = b.get("itemLabel", {}).get("value", qid)
        desc = b.get("desc", {}).get("value", "")
        coord = b.get("coord", {}).get("value", "")
        ymin = None
        if "inception" in b:
            try:
                ymin = int(b["inception"]["value"][:4])
            except Exception:
                pass
        rec = Record(
            source="wikidata",
            source_id=qid,
            title=label[:300],
            url_original=f"https://www.wikidata.org/wiki/{qid}",
            snippet=desc[:400],
            doc_type="entity",
            language="en",
            date_text=b.get("inception", {}).get("value", "")[:10] if "inception" in b else "",
            date_year_min=ymin,
            metadata={"qid": qid, "coord_wkt": coord, "country_qid": b.get("country", {}).get("value", "").rsplit("/", 1)[-1] if "country" in b else None},
        )
        out.append(rec)
    return out


# ---------- connector: Antenati (Italian civil records) ----------

async def search_antenati(session, query: str, limit: int = 20) -> list[Record]:
    """Antenati uses Solr-backed search. Try public search endpoint."""
    url = "https://antenati.cultura.gov.it/api/search"
    params = {"q": query, "size": limit}
    data = await fetch_json(session, url, params)
    if not data or not isinstance(data, dict):
        return []
    out = []
    for item in (data.get("results") or data.get("hits") or [])[:limit]:
        title = item.get("title", "") or item.get("name", "")
        ident = item.get("id", "") or item.get("uuid", "")
        rec = Record(
            source="antenati",
            source_id=str(ident),
            title=str(title)[:300],
            url_original=item.get("url", "") or f"https://antenati.cultura.gov.it/ark/{ident}",
            doc_type="civil_record",
            location=item.get("place", "") or item.get("location", ""),
            date_text=str(item.get("date", "")),
        )
        ymin, ymax = parse_year_range(rec.date_text)
        rec.date_year_min, rec.date_year_max = ymin, ymax
        out.append(rec)
    return out


# ---------- relevance scoring ----------

def score_record(rec: Record, query_terms: list[str]) -> float:
    """Boost: exact title match > snippet match > location match. Penalize if no date and no thumbnail."""
    score = 0.0
    title_l = (rec.title or "").lower()
    snip_l = (rec.snippet or "").lower()
    full_l = (rec.full_text or "").lower()
    for t in query_terms:
        tl = t.lower()
        if tl in title_l:
            score += 5.0
        if tl in snip_l:
            score += 2.0
        if tl in full_l:
            score += 1.5
        if rec.location and tl in rec.location.lower():
            score += 3.0
    # Boost for inscriptions about specific find spots
    if rec.source == "edh" and rec.location:
        score += 2.0
    # Boost if has date
    if rec.date_year_min:
        score += 0.5
    # Boost IIIF (richer content)
    if rec.url_iiif:
        score += 1.0
    return round(score, 2)


# ---------- main orchestrator ----------

CONNECTORS = {
    "europeana": search_europeana,
    "edh": search_edh,
    "internet_archive": search_internet_archive,
    "pelagios": search_pelagios,
    "wikidata": search_wikidata,
    "digivatlib": search_digivatlib,
    "antenati": search_antenati,
    "edr": search_edr,
}


async def run_search(query_terms: list[str], sources: list[str], per_source_limit: int = 30) -> list[Record]:
    """Run all sources in parallel for OR-expanded query string."""
    query = " OR ".join(f'"{t}"' for t in query_terms)
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        tasks = []
        for src in sources:
            fn = CONNECTORS.get(src)
            if fn:
                tasks.append(fn(session, query, per_source_limit))
        results = await asyncio.gather(*tasks, return_exceptions=True)
    all_recs: list[Record] = []
    for src, res in zip(sources, results):
        if isinstance(res, Exception):
            print(f"  ! {src}: {res}", file=sys.stderr)
            continue
        for r in res:
            r.relevance = score_record(r, query_terms)
            all_recs.append(r)
    # Dedupe by (source, source_id)
    seen = set()
    deduped = []
    for r in sorted(all_recs, key=lambda x: -x.relevance):
        key = (r.source, r.source_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ---------- output ----------

def write_jsonl(records: list[Record], query: str) -> Path:
    qhash = hashlib.sha256(query.encode()).hexdigest()[:12]
    ts = time.strftime("%Y-%m-%d-%H%M%S")
    fname = STAGING_DIR / f"{ts}-{qhash}.jsonl"
    with open(fname, "w") as f:
        for r in records:
            f.write(json.dumps({"query": query, **r.to_dict()}, ensure_ascii=False) + "\n")
    return fname


async def upload_supabase(records: list[Record], query: str, location_key: str = "") -> int:
    """Bulk-INSERT records into archive_results via Supabase REST. Requires SUPABASE_SERVICE_KEY env."""
    if not SUPABASE_SERVICE_KEY:
        print("  ! SUPABASE_SERVICE_KEY not set — skipping upload", file=sys.stderr)
        return 0
    qhash = hashlib.sha256(query.encode()).hexdigest()[:32]
    rows = []
    for r in records:
        rows.append({
            "query_text": query,
            "query_hash": qhash,
            "source": r.source,
            "source_id": r.source_id or None,
            "title": r.title,
            "author": r.author or None,
            "date_text": r.date_text or None,
            "date_year_min": r.date_year_min,
            "date_year_max": r.date_year_max,
            "location": r.location or location_key or None,
            "language": r.language or None,
            "doc_type": r.doc_type or None,
            "url_original": r.url_original,
            "url_iiif": r.url_iiif or None,
            "thumbnail_url": r.thumbnail_url or None,
            "snippet": r.snippet or None,
            "full_text": r.full_text or None,
            "metadata": r.metadata or {},
            "relevance": r.relevance,
            "tags": r.tags + ([location_key] if location_key else []),
        })
    url = f"{SUPABASE_URL}/rest/v1/archive_results"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates,return=minimal",
    }
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # Chunk to 100 rows per request
        n_uploaded = 0
        for i in range(0, len(rows), 100):
            chunk = rows[i:i+100]
            try:
                async with session.post(url, headers=headers, json=chunk) as r:
                    if r.status < 300:
                        n_uploaded += len(chunk)
                    else:
                        body = await r.text()
                        print(f"  ! Supabase upload {r.status}: {body[:200]}", file=sys.stderr)
            except Exception as e:
                print(f"  ! Supabase upload error: {e}", file=sys.stderr)
        return n_uploaded


def print_markdown(records: list[Record], query: str, top_n: int = 30):
    print(f"# Archive Search: {query}\n")
    print(f"Total results: **{len(records)}**, showing top {min(top_n, len(records))}\n")
    by_src: dict[str, int] = {}
    for r in records:
        by_src[r.source] = by_src.get(r.source, 0) + 1
    print("**Po izvoru:** " + ", ".join(f"{s}:{n}" for s, n in sorted(by_src.items(), key=lambda x: -x[1])))
    print()
    for i, r in enumerate(records[:top_n], 1):
        date = f" ({r.date_text})" if r.date_text else ""
        author = f" — {r.author}" if r.author else ""
        print(f"### {i}. [{r.source}] {r.title}{date}")
        if author:
            print(f"*{author.strip(' —')}*")
        if r.location:
            print(f"📍 {r.location}")
        if r.snippet:
            print(f"> {r.snippet[:300]}")
        print(f"🔗 {r.url_original}")
        if r.url_iiif:
            print(f"🖼️ IIIF: {r.url_iiif}")
        print(f"⭐ relevance: {r.relevance}\n")


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Federated archive search for Ulcinj region.")
    ap.add_argument("query", nargs="?", help='Free-text query (e.g. "Olcinium" or "Dulcigno pirate")')
    ap.add_argument("--location", help="Location key from regional-vocab.json (e.g. ulcinj, svac)")
    ap.add_argument("--source", action="append", help="Limit to source (europeana, edh, internet_archive, digivatlib, antenati). Repeatable.")
    ap.add_argument("--limit", type=int, default=30, help="Per-source limit (default 30)")
    ap.add_argument("--top", type=int, default=30, help="Top N to print in report")
    ap.add_argument("--harvest", action="store_true", help="Harvest all locations from vocab")
    ap.add_argument("--upload", action="store_true", help="Upload results to Supabase archive_results (needs $SUPABASE_SERVICE_KEY)")
    ap.add_argument("--quiet", action="store_true", help="Skip markdown report (JSONL only)")
    args = ap.parse_args()

    vocab = load_vocab()
    sources = args.source or list(CONNECTORS.keys())

    if args.harvest:
        asyncio.run(harvest_all(vocab, sources, args.limit, args.upload))
        return

    if args.location:
        terms = expand_location_query(args.location, vocab)
        query_label = f"location:{args.location}"
    elif args.query:
        terms = [args.query]
        query_label = args.query
    else:
        ap.error("Need either positional QUERY or --location KEY or --harvest")

    print(f"🔎 Searching {len(sources)} sources for: {terms}", file=sys.stderr)
    records = asyncio.run(run_search(terms, sources, args.limit))
    out_path = write_jsonl(records, query_label)
    print(f"💾 JSONL: {out_path}", file=sys.stderr)
    if args.upload:
        loc = args.location or ""
        n = asyncio.run(upload_supabase(records, query_label, loc))
        print(f"☁️  Supabase: {n} rows uploaded", file=sys.stderr)
    if not args.quiet:
        print_markdown(records, query_label, args.top)


async def harvest_all(vocab: dict, sources: list[str], per_source_limit: int, upload: bool = False):
    """Run a single search per primary location, save all to JSONL (and Supabase if --upload)."""
    locations = []
    for bucket in ("primary_locations", "regional_locations", "regions"):
        for key, entry in vocab.get(bucket, {}).items():
            if entry.get("priority") == "primary":
                locations.append(key)
    print(f"🌾 Harvest: {len(locations)} primary locations × {len(sources)} sources", file=sys.stderr)
    total_uploaded = 0
    for loc_key in locations:
        terms = expand_location_query(loc_key, vocab)
        if not terms:
            continue
        records = await run_search(terms, sources, per_source_limit)
        path = write_jsonl(records, f"harvest:{loc_key}")
        msg = f"  ✓ {loc_key}: {len(records)} hits → {path.name}"
        if upload and records:
            n = await upload_supabase(records, f"harvest:{loc_key}", loc_key)
            total_uploaded += n
            msg += f" (☁️ {n})"
        print(msg, file=sys.stderr)
        await asyncio.sleep(1.0)
    if upload:
        print(f"☁️  Total uploaded to Supabase: {total_uploaded}", file=sys.stderr)


if __name__ == "__main__":
    main()
