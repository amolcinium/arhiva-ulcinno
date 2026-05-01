#!/usr/bin/env python3
"""
Snippet enrichment — refetches records with empty/short snippets and updates Supabase.

Run:
  export SUPABASE_SERVICE_KEY="..."
  python3 enrich_snippets.py
"""
import asyncio
import json
import os
import re
import sys
import urllib.request
from urllib.parse import quote_plus

import aiohttp

SUPABASE_URL = "https://frsgzfzvdxswqjpdmcsd.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
UA = "arhiva-ulcinno-enricher/1.0 (+https://arhiva.ulcinno.com)"


def fetch_records(source: str, limit: int = 200) -> list[dict]:
    """Fetch records from Supabase that need enrichment."""
    url = (f"{SUPABASE_URL}/rest/v1/archive_results"
           f"?source=eq.{source}&or=(snippet.is.null,snippet.eq.)"
           f"&select=id,source_id,title,location,metadata,url_original&limit={limit}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def patch_record(rid: str, snippet: str):
    """Update one record's snippet field."""
    url = f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}"
    body = json.dumps({"snippet": snippet[:1500]}).encode()
    req = urllib.request.Request(
        url, data=body, method="PATCH",
        headers={**HEADERS, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(req)


# ----- per-source enrichment functions -----

async def enrich_edh(session, rec) -> str:
    """EDH: build snippet from findspot + coords + Pleiades/Trismegistos refs."""
    md = rec.get("metadata") or {}
    parts = []
    name = rec.get("location") or rec.get("title", "").replace("Findspot: ", "")
    if name:
        parts.append(f"Antička lokacija {name}")
    lng, lat = md.get("longitude"), md.get("latitude")
    if lng and lat:
        parts.append(f"koordinate {lat:.4f}°N, {lng:.4f}°E")
    if md.get("pleiades_uri"):
        parts.append("Pleiades referenca dostupna")
    if md.get("trismegistos_uri"):
        parts.append("Trismegistos referenca dostupna")
    parts.append("Klikni link da vidiš sve rimske natpise sa ove lokacije u EDH bazi.")
    return ". ".join(parts) + "."


async def enrich_europeana(session, rec) -> str:
    """Europeana: fetch full record via /record/v2/{id}.json with profile=rich."""
    sid = rec.get("source_id", "")
    if not sid:
        return ""
    url = f"https://api.europeana.eu/record/v2{sid}.json"
    params = {"wskey": "apidemo", "profile": "rich"}
    try:
        async with session.get(url, params=params, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return ""
            data = await r.json(content_type=None)
    except Exception:
        return ""
    obj = data.get("object", {})
    proxies = obj.get("proxies", [{}])
    descs = []
    for p in proxies:
        d = p.get("dcDescription", {})
        if isinstance(d, dict):
            for lang_vals in d.values():
                if isinstance(lang_vals, list):
                    descs.extend(lang_vals)
    if not descs:
        # Fallback: subject keywords + creator + date
        subjs = []
        for p in proxies:
            s = p.get("dcSubject", {})
            if isinstance(s, dict):
                for vs in s.values():
                    if isinstance(vs, list):
                        subjs.extend(vs)
        creators = obj.get("agents", [])
        cnames = [a.get("prefLabel", {}).get("en", [""])[0] if isinstance(a.get("prefLabel"), dict) else ""
                  for a in creators[:3]]
        type_ = obj.get("type", "")
        bits = [type_] + [s for s in subjs[:5] if s] + [c for c in cnames if c]
        if bits:
            return " · ".join(b for b in bits if b)[:600]
        return ""
    return " / ".join(d.strip() for d in descs[:3] if d)[:1500]


async def enrich_internet_archive(session, rec) -> str:
    """Internet Archive: fetch /metadata/{id}.json for richer description."""
    sid = rec.get("source_id", "")
    if not sid:
        return ""
    url = f"https://archive.org/metadata/{sid}"
    try:
        async with session.get(url, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return ""
            data = await r.json(content_type=None)
    except Exception:
        return ""
    md = data.get("metadata", {})
    desc = md.get("description", "")
    if isinstance(desc, list):
        desc = " ".join(desc)
    if not desc:
        # Fallback: subject + creator + collection
        subj = md.get("subject", "")
        if isinstance(subj, list):
            subj = ", ".join(subj[:5])
        creator = md.get("creator", "")
        if isinstance(creator, list):
            creator = ", ".join(creator[:3])
        bits = [creator, subj]
        return " · ".join(b for b in bits if b)[:600]
    # Strip HTML tags simply
    desc = re.sub(r"<[^>]+>", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc[:1500]


async def enrich_gallica(session, rec) -> str:
    """Gallica: fetch full DC record via /ark URL + .json or use SRU per ID."""
    sid = rec.get("source_id", "")
    if not sid:
        return ""
    # Try OAI-PMH GetRecord
    url = "https://gallica.bnf.fr/services/OAIRecord"
    params = {"ark": sid if sid.startswith("ark:") else f"ark:/12148/{sid}"}
    try:
        async with session.get(url, params=params, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return ""
            text = await r.text()
    except Exception:
        return ""
    # Extract dc:description from XML
    desc_m = re.search(r"<dc:description[^>]*>(.*?)</dc:description>", text, re.S)
    if desc_m:
        return desc_m.group(1).strip()[:1500]
    # Fallback: dc:subject + dc:type + dc:format
    subjs = re.findall(r"<dc:subject[^>]*>(.*?)</dc:subject>", text, re.S)
    types = re.findall(r"<dc:type[^>]*>(.*?)</dc:type>", text, re.S)
    bits = [s.strip() for s in (types[:2] + subjs[:5]) if s.strip()]
    return " · ".join(bits)[:600]


async def enrich_wellcome(session, rec) -> str:
    """Wellcome: refetch full work via /works/{id} with include=description,subjects,production."""
    sid = rec.get("source_id", "")
    if not sid:
        return ""
    url = f"https://api.wellcomecollection.org/catalogue/v2/works/{sid}"
    params = {"include": "subjects,production,contributors,notes,genres"}  # description returned by default
    try:
        async with session.get(url, params=params, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return ""
            data = await r.json(content_type=None)
    except Exception:
        return ""
    desc = data.get("description") or ""
    if desc:
        return re.sub(r"\s+", " ", desc).strip()[:1500]
    # Compose richer fallback from subjects + contributors + production places + genres + notes
    bits = []
    contribs = [c.get("agent", {}).get("label", "") for c in data.get("contributors", [])][:3]
    contribs = [c for c in contribs if c]
    if contribs:
        bits.append("Author: " + ", ".join(contribs))
    prod_places = []
    for p in data.get("production", []):
        for pl in p.get("places", []):
            if pl.get("label"):
                prod_places.append(pl["label"])
    if prod_places:
        bits.append("Published: " + ", ".join(prod_places[:3]))
    subjs = [s.get("label", "") for s in data.get("subjects", [])][:6]
    subjs = [s for s in subjs if s]
    if subjs:
        bits.append("Subjects: " + ", ".join(subjs))
    genres = [g.get("label", "") for g in data.get("genres", [])][:3]
    genres = [g for g in genres if g]
    if genres:
        bits.append("Genre: " + ", ".join(genres))
    notes = data.get("notes", [])
    note_text = ""
    for n in notes:
        for c in n.get("contents", []):
            if isinstance(c, str):
                note_text += c + " "
    if note_text.strip():
        bits.append(note_text.strip()[:300])
    return " · ".join(bits)[:1500]


async def enrich_wikidata(session, rec) -> str:
    """Wikidata: refetch entity for description in any language."""
    qid = rec.get("source_id", "")
    if not qid:
        return ""
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    try:
        async with session.get(url, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return ""
            data = await r.json(content_type=None)
    except Exception:
        return ""
    ent = data.get("entities", {}).get(qid, {})
    descs = ent.get("descriptions", {})
    for lang in ("en", "sh", "hr", "sr", "bs", "it", "la", "sq", "de", "fr"):
        if lang in descs:
            return descs[lang].get("value", "")[:1500]
    if descs:
        return list(descs.values())[0].get("value", "")[:1500]
    return ""


ENRICHERS = {
    "edh": enrich_edh,
    "europeana": enrich_europeana,
    "internet_archive": enrich_internet_archive,
    "gallica": enrich_gallica,
    "wellcome": enrich_wellcome,
    "wikidata": enrich_wikidata,
}


# ----- runner -----

async def enrich_source(source: str):
    print(f"\n=== {source} ===", flush=True)
    records = fetch_records(source, limit=300)
    print(f"  {len(records)} records to enrich")
    if not records:
        return
    fn = ENRICHERS.get(source)
    if not fn:
        print(f"  no enricher for {source}")
        return
    timeout = aiohttp.ClientTimeout(total=30)
    updated = 0
    skipped = 0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Process sequentially to avoid hammering source APIs (especially Europeana w/ apidemo key)
        for i, rec in enumerate(records):
            try:
                snippet = await fn(session, rec)
                if snippet and len(snippet) > 30:
                    patch_record(rec["id"], snippet)
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1
                if i < 3:
                    print(f"  ! {rec.get('id')}: {e}")
            if (i + 1) % 25 == 0:
                print(f"  ... {i + 1}/{len(records)} ({updated} updated)")
            # brief delay to respect rate limits
            if source in ("europeana", "internet_archive"):
                await asyncio.sleep(0.15)
    print(f"  ✓ {source}: {updated} updated, {skipped} skipped")


async def main():
    for source in ["edh", "wikidata", "gallica", "wellcome", "internet_archive", "europeana"]:
        try:
            await enrich_source(source)
        except Exception as e:
            print(f"  !! {source} failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
