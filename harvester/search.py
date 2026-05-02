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
import xml.etree.ElementTree as ET
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


# ---------- connector: CrossRef (academic articles) ----------

async def search_crossref(session, query: str, limit: int = 20) -> list[Record]:
    """CrossRef — academic literature index. Finds journal articles, book chapters mentioning Ulcinj/Olcinium."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:6]
    qstr = " ".join(terms)
    url = "https://api.crossref.org/works"
    params = {"query": qstr, "rows": limit, "select": "DOI,title,author,published-print,published-online,abstract,publisher,type,subject,URL,container-title"}
    data = await fetch_json(session, url, params)
    if not data:
        return []
    out = []
    for item in data.get("message", {}).get("items", []):
        doi = item.get("DOI", "")
        title = item.get("title", [""])[0] if item.get("title") else ""
        if not doi or not title:
            continue
        authors_list = item.get("author", []) or []
        authors = ", ".join(f"{a.get('given','')} {a.get('family','')}".strip() for a in authors_list[:3])
        date_parts = (item.get("published-print", {}) or item.get("published-online", {}) or {}).get("date-parts", [[None]])
        ymin = date_parts[0][0] if date_parts and date_parts[0] else None
        # Strip JATS XML tags from abstract
        abstract = item.get("abstract", "")
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
        container = item.get("container-title", [""])[0] if item.get("container-title") else ""
        rec = Record(
            source="crossref",
            source_id=doi,
            title=title[:300],
            author=authors[:200],
            date_text=str(ymin) if ymin else "",
            date_year_min=ymin,
            date_year_max=ymin,
            url_original=item.get("URL", f"https://doi.org/{doi}"),
            snippet=abstract[:1500],
            doc_type=item.get("type", "article"),
            metadata={"doi": doi, "publisher": item.get("publisher"), "journal": container},
        )
        out.append(rec)
    return out


# ---------- connector: Open Library ----------

async def search_openlibrary(session, query: str, limit: int = 20) -> list[Record]:
    """Open Library — book metadata sister of Internet Archive. Catalogs millions of books."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    qstr = " OR ".join(terms)
    url = "https://openlibrary.org/search.json"
    params = {"q": qstr, "limit": limit, "fields": "key,title,author_name,first_publish_year,subject,publisher,isbn,language,cover_i,ia"}
    data = await fetch_json(session, url, params)
    if not data:
        return []
    out = []
    for item in data.get("docs", []):
        key = item.get("key", "")
        title = item.get("title", "")
        if not key or not title:
            continue
        ymin = item.get("first_publish_year")
        authors = ", ".join(item.get("author_name", [])[:3])
        subjs = ", ".join(item.get("subject", [])[:5])
        cover = f"https://covers.openlibrary.org/b/id/{item['cover_i']}-M.jpg" if item.get("cover_i") else ""
        rec = Record(
            source="openlibrary",
            source_id=key.lstrip("/"),
            title=title[:300],
            author=authors[:200],
            date_text=str(ymin) if ymin else "",
            date_year_min=ymin,
            date_year_max=ymin,
            url_original=f"https://openlibrary.org{key}",
            thumbnail_url=cover,
            snippet=subjs[:600],
            doc_type="book",
            language=", ".join(item.get("language", [])[:3])[:30],
            metadata={"isbn": item.get("isbn", [None])[0] if item.get("isbn") else None,
                     "ia_id": item.get("ia", [None])[0] if item.get("ia") else None,
                     "publisher": ", ".join(item.get("publisher", [])[:2])},
        )
        out.append(rec)
    return out


# ---------- connector: HathiTrust (US academic library) ----------

async def search_hathitrust(session, query: str, limit: int = 15) -> list[Record]:
    """HathiTrust — massive US academic digital library. Bibliographic API for catalog records."""
    # HathiTrust does not have a great free-text search; use OCLC lookup via title
    # We use their proxied search via babel.hathitrust.org full-text but JSON often blocked
    # Alternative: search via Internet Archive (which mirrors HathiTrust) is already covered
    # For now: use bibliographic API with author/title queries
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:3]
    out: list[Record] = []
    for term in terms:
        # HathiTrust public search via Solr endpoint
        url = "https://catalog.hathitrust.org/Search/Home"
        params = {"lookfor": term, "type": "all", "format": "json"}
        text = await fetch_text(session, url, params)
        if not text:
            continue
        # The HTML endpoint won't return JSON; instead try bib metadata endpoint
        # Skip — yield was minimal in probe
        break
    return out  # placeholder; real HathiTrust integration requires their proper API key for searches


# ---------- connector: Norwegian National Library (NB.no) ----------

async def search_nb(session, query: str, limit: int = 15) -> list[Record]:
    """Norwegian National Library — surprisingly has Adriatic-related content (travelogues, cartography)."""
    url = "https://api.nb.no/catalog/v1/items"
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    qstr = " OR ".join(terms)
    params = {"q": qstr, "size": limit}
    data = await fetch_json(session, url, params)
    if not data:
        return []
    out = []
    items = data.get("_embedded", {}).get("items", [])
    for item in items:
        md = item.get("metadata", {})
        title = md.get("title", "")
        nb_id = item.get("id", "")
        if not title or not nb_id:
            continue
        creators_raw = md.get("creators") or []
        if not isinstance(creators_raw, list):
            creators_raw = [creators_raw] if creators_raw else []
        author = ", ".join(
            c if isinstance(c, str) else (c.get("name") or c.get("label") or str(c))
            for c in creators_raw[:3]
        )
        ymin = None
        date_str = ""
        for d in [md.get("originiso", ""), md.get("startdate", ""), md.get("originalAvailableDate", "")]:
            if d:
                date_str = str(d)
                m = re.search(r'\b(1[5-9]\d{2}|20\d{2})\b', date_str)
                if m:
                    ymin = int(m.group(1))
                    break
        thumb = ""
        if item.get("_links", {}).get("thumbnail_custom", {}).get("href"):
            thumb = item["_links"]["thumbnail_custom"]["href"]
        rec = Record(
            source="nb_no",
            source_id=nb_id,
            title=title[:300],
            author=author[:200],
            date_text=date_str[:50],
            date_year_min=ymin,
            date_year_max=ymin,
            url_original=item.get("_links", {}).get("presentation", {}).get("href", f"https://www.nb.no/items/{nb_id}"),
            thumbnail_url=thumb,
            snippet=(", ".join(
                s if isinstance(s, str) else (s.get("label") or s.get("name") or str(s))
                for s in (md["subjects"][:5] if isinstance(md.get("subjects"), list) else [])
            ) or "")[:500],
            doc_type=md.get("mediaType", "")[:50],
            language=", ".join(md.get("languages", [])[:2])[:30],
            metadata={"institution": "Norwegian National Library"},
        )
        out.append(rec)
    return out


# ---------- connector: Smithsonian Open Access ----------

async def search_smithsonian(session, query: str, limit: int = 15) -> list[Record]:
    """Smithsonian Open Access — anthropological/photographic collections. DEMO_KEY OK for low volume."""
    url = "https://api.si.edu/openaccess/api/v1.0/search"
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:4]
    qstr = " OR ".join(terms)
    params = {"api_key": "DEMO_KEY", "q": qstr, "rows": limit}
    data = await fetch_json(session, url, params)
    if not data:
        return []
    out = []
    for item in data.get("response", {}).get("rows", []):
        sid = item.get("id", "")
        title = item.get("title", "")
        if not sid or not title:
            continue
        content = item.get("content", {})
        descn = content.get("freetext", {}).get("notes", [])
        snippet = ""
        if isinstance(descn, list) and descn:
            snippet = (descn[0].get("content", "") if isinstance(descn[0], dict) else str(descn[0]))[:500]
        url_orig = item.get("url", "") or content.get("descriptiveNonRepeating", {}).get("record_link", "")
        rec = Record(
            source="smithsonian",
            source_id=sid,
            title=title[:300],
            url_original=url_orig or f"https://collections.si.edu/search/results.htm?q=record_ID:{sid}",
            snippet=snippet,
            doc_type=item.get("type", ""),
            metadata={"unitCode": item.get("unitCode", ""), "institution": "Smithsonian"},
        )
        out.append(rec)
    return out


# ---------- connector: BnF Gallica (France) ----------

async def search_gallica(session, query: str, limit: int = 30) -> list[Record]:
    """BnF Gallica SRU search — French national library (kartografija, putopisi, italijanski/franc. izvori o Jadranu)."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    out: list[Record] = []
    for term in terms:
        sru_query = f'dc.title all "{term}" or dc.subject all "{term}"'
        url = "https://gallica.bnf.fr/SRU"
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "query": sru_query,
            "maximumRecords": limit // max(len(terms), 1) + 2,
            "recordSchema": "dublincore",
        }
        text = await fetch_text(session, url, params)
        if not text:
            continue
        # Parse XML — extract dc:title, dc:creator, dc:date, dc:identifier
        records = re.findall(r'<srw:record>(.*?)</srw:record>', text, re.S)
        for rxml in records:
            title_m = re.search(r'<dc:title[^>]*>(.*?)</dc:title>', rxml, re.S)
            creator_m = re.search(r'<dc:creator[^>]*>(.*?)</dc:creator>', rxml, re.S)
            date_m = re.search(r'<dc:date[^>]*>(.*?)</dc:date>', rxml, re.S)
            id_m = re.search(r'<dc:identifier[^>]*>(https?://gallica\.bnf\.fr/[^<]+)</dc:identifier>', rxml)
            desc_m = re.search(r'<dc:description[^>]*>(.*?)</dc:description>', rxml, re.S)
            lang_m = re.search(r'<dc:language[^>]*>(.*?)</dc:language>', rxml, re.S)
            if not id_m or not title_m:
                continue
            url_orig = id_m.group(1).strip()
            ark_id = re.search(r'(ark:[^/]+/[^/]+)', url_orig)
            source_id = ark_id.group(1) if ark_id else url_orig.rsplit('/', 1)[-1]
            ymin, ymax = parse_year_range(date_m.group(1) if date_m else "")
            iiif = ""
            if "ark:" in url_orig:
                iiif = url_orig.replace("https://gallica.bnf.fr/", "https://gallica.bnf.fr/iiif/") + "/manifest.json" if "/manifest" not in url_orig else url_orig
            rec = Record(
                source="gallica",
                source_id=source_id,
                title=title_m.group(1).strip()[:300],
                author=(creator_m.group(1).strip() if creator_m else "")[:200],
                date_text=(date_m.group(1).strip() if date_m else "")[:50],
                date_year_min=ymin,
                date_year_max=ymax,
                url_original=url_orig,
                url_iiif=iiif,
                snippet=(desc_m.group(1).strip() if desc_m else "")[:400],
                doc_type="book",
                language=(lang_m.group(1).strip() if lang_m else "fr")[:10],
                metadata={"matched_term": term, "institution": "BnF"},
            )
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


# ---------- connector: Library of Congress (USA) ----------

async def search_loc(session, query: str, limit: int = 30) -> list[Record]:
    """Library of Congress JSON search — američka kongresna biblioteka, ima dosta mapa i putopisa o Jadranu."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    out: list[Record] = []
    for term in terms:
        url = "https://www.loc.gov/search/"
        params = {"q": term, "fo": "json", "c": str(limit // max(len(terms), 1) + 2)}
        data = await fetch_json(session, url, params)
        if not data:
            continue
        for item in data.get("results", []):
            title = item.get("title", "")
            if isinstance(title, list):
                title = title[0] if title else ""
            url_orig = item.get("url") or item.get("id", "")
            if not url_orig or not title:
                continue
            date_raw = item.get("date") or ""
            ymin, ymax = parse_year_range(str(date_raw))
            thumb = ""
            if isinstance(item.get("image_url"), list) and item["image_url"]:
                thumb = item["image_url"][0]
            elif isinstance(item.get("image_url"), str):
                thumb = item["image_url"]
            descs = item.get("description") or []
            snippet = (descs[0] if isinstance(descs, list) and descs else str(descs))[:400]
            iiif = ""
            if isinstance(item.get("resources"), list) and item["resources"]:
                for res in item["resources"]:
                    if isinstance(res, dict) and "iiif_manifest" in res:
                        iiif = res["iiif_manifest"]
                        break
            rec = Record(
                source="loc",
                source_id=str(item.get("id", url_orig.rsplit("/", 1)[-1])),
                title=str(title)[:300],
                date_text=str(date_raw)[:50],
                date_year_min=ymin,
                date_year_max=ymax,
                url_original=url_orig,
                url_iiif=iiif,
                thumbnail_url=thumb,
                snippet=snippet,
                doc_type=str(item.get("original_format", [""])[0] if isinstance(item.get("original_format"), list) else "")[:50],
                language=str((item.get("language") or [""])[0] if isinstance(item.get("language"), list) else "")[:10],
                metadata={"matched_term": term, "institution": "Library of Congress"},
            )
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


# ---------- connector: Wellcome Collection (UK) ----------

async def search_wellcome(session, query: str, limit: int = 20) -> list[Record]:
    """Wellcome Collection (London) — putopisi, antropologija, medicina XIX vijeka. Manji yield ali kvalitetan."""
    url = "https://api.wellcomecollection.org/catalogue/v2/works"
    # Wellcome supports OR in single query
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:6]
    qstr = " OR ".join(terms)
    params = {"query": qstr, "pageSize": limit, "include": "images,production"}
    data = await fetch_json(session, url, params)
    if not data:
        return []
    out = []
    for item in data.get("results", []):
        wid = item.get("id", "")
        title = item.get("title", "")
        if not wid or not title:
            continue
        prod = item.get("production", [])
        date_raw = ""
        ymin = ymax = None
        if prod and isinstance(prod, list) and prod[0].get("dates"):
            d = prod[0]["dates"][0]
            date_raw = d.get("label", "")
            ymin, ymax = parse_year_range(date_raw)
        thumb = ""
        if item.get("thumbnail"):
            thumb = item["thumbnail"].get("url", "")
        rec = Record(
            source="wellcome",
            source_id=wid,
            title=title[:300],
            date_text=date_raw[:50],
            date_year_min=ymin,
            date_year_max=ymax,
            url_original=f"https://wellcomecollection.org/works/{wid}",
            thumbnail_url=thumb,
            snippet=(item.get("description") or "")[:400],
            doc_type=(item.get("workType") or {}).get("label", "") if isinstance(item.get("workType"), dict) else "",
            metadata={"institution": "Wellcome Collection", "iiif_present": bool(item.get("images"))},
        )
        out.append(rec)
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


# ---------- connector: BSB Bayerische Staatsbibliothek ----------

async def search_bsb(session, query: str, limit: int = 20) -> list[Record]:
    """Bayerische Staatsbibliothek Munich — SRU catalog for digitized items (cartography, travelogues)."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    qstr = " OR ".join(f'any="{t}"' for t in terms)
    url = "https://opacplus.bsb-muenchen.de/TouchPoint/sru/DB=1/"
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": qstr,
        "maximumRecords": min(limit, 50),
        "recordSchema": "dc",
    }
    text = await fetch_text(session, url, params)
    if not text:
        return []
    out: list[Record] = []
    try:
        root = ET.fromstring(text)
        ns = {
            "srw": "http://www.loc.gov/zing/srw/",
            "dc": "http://purl.org/dc/elements/1.1/",
            "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
        }
        for record in root.findall(".//srw:record", ns):
            data_elem = record.find(".//oai_dc:dc", ns)
            if data_elem is None:
                continue

            def _txt(tag: str) -> str:
                e = data_elem.find(f"dc:{tag}", ns)
                return (e.text or "").strip() if e is not None else ""

            def _txts(tag: str) -> list[str]:
                return [(e.text or "").strip() for e in data_elem.findall(f"dc:{tag}", ns) if e.text]

            title = _txt("title")
            if not title:
                continue
            identifier = _txt("identifier")
            url_orig = (
                identifier if identifier.startswith("http")
                else f"https://www.digitale-sammlungen.de/de/search?q={quote_plus(title)}"
            )
            authors = _txts("creator")
            date_str = _txt("date")
            subjects = _txts("subject")
            description = _txt("description")
            ymin, ymax = parse_year_range(date_str)
            rec = Record(
                source="bsb",
                source_id=(
                    hashlib.md5(identifier.encode()).hexdigest()[:16]
                    if identifier else hashlib.md5(title.encode()).hexdigest()[:16]
                ),
                title=title[:300],
                author=", ".join(authors[:3])[:200],
                date_text=date_str[:50],
                date_year_min=ymin,
                date_year_max=ymax,
                url_original=url_orig,
                snippet=(", ".join(subjects[:5]) or description)[:500],
                language=_txt("language")[:20],
                doc_type=_txt("type")[:50],
                metadata={
                    "institution": "Bayerische Staatsbibliothek",
                    "publisher": _txt("publisher"),
                },
            )
            out.append(rec)
    except ET.ParseError as e:
        print(f"  ! BSB XML parse error: {e}", file=sys.stderr)
    return out[:limit]


# ---------- connector: SLUB Dresden ----------

async def search_slub(session, query: str, limit: int = 20) -> list[Record]:
    """SLUB Dresden — VuFind catalog API for Saxon manuscripts, maps and early prints."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:5]
    qstr = " ".join(terms)
    # VuFind JSON API
    url = "https://katalog.slub-dresden.de/api/v1/search"
    params = {
        "lookfor": qstr,
        "type": "AllFields",
        "limit": min(limit, 40),
        "sort": "relevance",
    }
    data = await fetch_json(session, url, params)
    if not data or not isinstance(data, dict):
        return []
    out: list[Record] = []
    for item in (data.get("records") or data.get("results") or [])[:limit]:
        title_raw = item.get("title", "") or item.get("title_full", "")
        title = (title_raw if isinstance(title_raw, str) else " ".join(title_raw or []))[:300]
        if not title:
            continue
        record_id = str(item.get("id", ""))
        authors_raw = item.get("author", "") or item.get("author2", []) or []
        if isinstance(authors_raw, str):
            author = authors_raw[:200]
        else:
            author = ", ".join(str(a) for a in authors_raw[:3])[:200]
        date_str = str(item.get("publishDate", [""])[0] if isinstance(item.get("publishDate"), list) else item.get("publishDate", ""))
        ymin, ymax = parse_year_range(date_str)
        subjects_raw = item.get("topic", []) or item.get("subject", []) or []
        snippet = ", ".join(str(s) for s in subjects_raw[:5])[:500]
        thumb = ""
        if item.get("cover"):
            thumb = str(item["cover"])
        url_orig = (
            f"https://katalog.slub-dresden.de/id/{record_id}"
            if record_id else f"https://katalog.slub-dresden.de/Search/Results?lookfor={quote_plus(qstr)}"
        )
        url_iiif = ""
        for link in (item.get("urls") or []):
            href = link.get("url", "") if isinstance(link, dict) else str(link)
            if "digital.slub-dresden.de" in href or "iiif" in href.lower():
                url_iiif = href
                break
        rec = Record(
            source="slub",
            source_id=record_id or hashlib.md5(title.encode()).hexdigest()[:16],
            title=title,
            author=author,
            date_text=date_str[:50],
            date_year_min=ymin,
            date_year_max=ymax,
            url_original=url_orig,
            url_iiif=url_iiif,
            thumbnail_url=thumb,
            snippet=snippet,
            language=str(item.get("language", [""])[0] if isinstance(item.get("language"), list) else item.get("language", ""))[:20],
            doc_type=str(item.get("format", [""])[0] if isinstance(item.get("format"), list) else item.get("format", ""))[:50],
            metadata={"institution": "SLUB Dresden", "publisher": str(item.get("publisher", ""))[:100]},
        )
        out.append(rec)
    return out


# ---------- connector: Manus Online (Italian manuscripts) ----------

async def search_manus(session, query: str, limit: int = 20) -> list[Record]:
    """Manus Online (ICCU) — Italian manuscript database. REST search with HTML fallback."""
    terms = [t.strip().strip('"') for t in re.split(r'\s+OR\s+', query) if t.strip()][:3]
    qstr = " ".join(terms)
    out: list[Record] = []

    # Try JSON API first
    url_json = "https://manus.iccu.sbn.it/json/ricerca"
    params = {"testo": qstr, "rows": min(limit, 30), "start": 0}
    data = await fetch_json(session, url_json, params)
    if data and isinstance(data, dict):
        items = data.get("manoscritti") or data.get("items") or data.get("results") or []
        for item in items[:limit]:
            title = (item.get("segnatura") or item.get("titolo") or item.get("title") or "")[:300]
            if not title:
                continue
            rec_id = str(item.get("id") or item.get("codice") or hashlib.md5(title.encode()).hexdigest()[:16])
            date_str = str(item.get("datazione") or item.get("data") or "")
            ymin, ymax = parse_year_range(date_str)
            rec = Record(
                source="manus",
                source_id=rec_id,
                title=title,
                author=str(item.get("autore") or item.get("author") or "")[:200],
                date_text=date_str[:50],
                date_year_min=ymin,
                date_year_max=ymax,
                location=str(item.get("luogo_conservazione") or item.get("location") or "")[:200],
                url_original=str(item.get("url") or f"https://manus.iccu.sbn.it/opac_SchedaScheda.php?ID={rec_id}"),
                snippet=str(item.get("abstract") or item.get("descrizione") or "")[:500],
                doc_type="manuscript",
                metadata={"institution": "ICCU Manus Online", "biblioteca": str(item.get("biblioteca") or "")},
            )
            out.append(rec)
        if out:
            return out

    # Fallback: parse HTML search results
    url_html = "https://manus.iccu.sbn.it/opac_SchedaScheda.php"
    params_html = {"q": qstr, "Tipo": "testoLibero", "PAGINAATTUALE": 1}
    html = await fetch_text(session, url_html, params_html)
    if not html:
        return []
    # Extract basic title/link pairs from HTML table rows
    rows = re.findall(r'href="(opac_SchedaScheda\.php\?[^"]+)"[^>]*>\s*([^<]{5,200})', html)
    for href, title_raw in rows[:limit]:
        title = re.sub(r'\s+', ' ', title_raw).strip()
        if not title:
            continue
        id_m = re.search(r'ID=(\d+)', href)
        rec_id = id_m.group(1) if id_m else hashlib.md5(title.encode()).hexdigest()[:12]
        rec = Record(
            source="manus",
            source_id=rec_id,
            title=title[:300],
            url_original=f"https://manus.iccu.sbn.it/{href}",
            doc_type="manuscript",
            metadata={"institution": "ICCU Manus Online"},
        )
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
    "gallica": search_gallica,
    "loc": search_loc,
    "wellcome": search_wellcome,
    "crossref": search_crossref,
    "openlibrary": search_openlibrary,
    "nb_no": search_nb,
    "smithsonian": search_smithsonian,
    "digivatlib": search_digivatlib,
    "antenati": search_antenati,
    "edr": search_edr,
    "bsb": search_bsb,
    "slub": search_slub,
    "manus": search_manus,
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
