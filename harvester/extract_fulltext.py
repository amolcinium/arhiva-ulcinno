#!/usr/bin/env python3
"""
Nivo 2 — Full-text page extraction.

For each Internet Archive (mediatype=texts) and BnF Gallica record:
  - Fetch the OCR'd full text of the document
  - Find paragraphs containing regional terms (Ulcinj, Olcinium, Dulcigno, etc.)
  - Extract 2-3 sentences of surrounding context per match
  - Update the record's `full_text` field in Supabase

Run:
  export SUPABASE_SERVICE_KEY="..."
  python3 extract_fulltext.py
"""
import asyncio
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import aiohttp

SUPABASE_URL = "https://frsgzfzvdxswqjpdmcsd.supabase.co"
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
UA = "arhiva-ulcinno-fulltext/1.0 (+https://arhiva.ulcinno.com)"
SKILL_DIR = Path(__file__).parent

# Load regional vocab to know what to highlight
VOCAB = json.loads((SKILL_DIR / "regional-vocab.json").read_text())

# Build a flat list of all regional terms we want to find in full text
def build_term_list() -> list[str]:
    terms = set()
    for bucket in ("primary_locations", "regional_locations", "regions"):
        for entry in VOCAB.get(bucket, {}).values():
            for t in entry.get("modern", []) + entry.get("historical", []):
                if len(t) >= 4:  # skip very short like "Bar" alone (too many false positives)
                    terms.add(t)
    # Always include core anchors (even if short)
    for t in ["Ulcinj", "Ulqin", "Olcinium", "Dulcigno", "Bojana", "Buna", "Svač", "Bar"]:
        terms.add(t)
    return sorted(terms, key=len, reverse=True)

ALL_TERMS = build_term_list()
TERM_PATTERN = re.compile("|".join(re.escape(t) for t in ALL_TERMS), re.IGNORECASE)


def fetch_records(source: str, limit: int = 200) -> list[dict]:
    """Fetch records that need full_text enrichment."""
    if source == "internet_archive":
        url = (f"{SUPABASE_URL}/rest/v1/archive_results"
               f"?source=eq.{source}&doc_type=eq.texts&or=(full_text.is.null,full_text.eq.)"
               f"&select=id,source_id,title,location&limit={limit}")
    else:
        url = (f"{SUPABASE_URL}/rest/v1/archive_results"
               f"?source=eq.{source}&or=(full_text.is.null,full_text.eq.)"
               f"&select=id,source_id,title,location&limit={limit}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def patch_full_text(rid: str, full_text: str):
    url = f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}"
    body = json.dumps({"full_text": full_text[:5000]}).encode()
    req = urllib.request.Request(
        url, data=body, method="PATCH",
        headers={**HEADERS, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(req)


def extract_context(text: str, max_excerpts: int = 5, window: int = 220) -> str:
    """Find term matches in text and extract sentence-level context around each."""
    if not text:
        return ""
    matches = list(TERM_PATTERN.finditer(text))
    if not matches:
        return ""
    # Dedupe overlapping matches and limit count
    seen_positions = set()
    excerpts = []
    for m in matches:
        # Skip if too close to a previous match (within window/2)
        if any(abs(m.start() - p) < window // 2 for p in seen_positions):
            continue
        seen_positions.add(m.start())
        # Extract context around match
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        excerpt = text[start:end].strip()
        # Find nearest sentence boundaries
        # Trim leading partial sentence
        first_period = excerpt.find('. ')
        if 0 < first_period < window // 2:
            excerpt = excerpt[first_period + 2:]
        # Trim trailing partial sentence
        last_period = excerpt.rfind('. ')
        if last_period > len(excerpt) - window // 2 and last_period > window:
            excerpt = excerpt[:last_period + 1]
        # Clean whitespace and OCR artifacts
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        excerpt = excerpt.replace("- ", "")  # OCR line-break hyphens
        if len(excerpt) > 60:
            excerpts.append(f"…{excerpt}…")
        if len(excerpts) >= max_excerpts:
            break
    return "\n\n".join(excerpts)


# ---- Internet Archive ----

async def get_ia_djvu_url(session, item_id: str) -> str | None:
    """Find the djvu.txt download URL for an IA item."""
    url = f"https://archive.org/metadata/{item_id}/files"
    try:
        async with session.get(url, headers={"User-Agent": UA}) as r:
            if r.status >= 400:
                return None
            data = await r.json(content_type=None)
    except Exception:
        return None
    for f in data.get("result", []):
        name = f.get("name", "")
        fmt = f.get("format", "")
        if name.endswith("_djvu.txt") or fmt == "DjVuTXT":
            return f"https://archive.org/download/{item_id}/{name}"
    return None


async def extract_ia(session, rec) -> str:
    """Download djvu.txt for IA item, extract regional-term context."""
    item_id = rec.get("source_id", "")
    if not item_id:
        return ""
    txt_url = await get_ia_djvu_url(session, item_id)
    if not txt_url:
        return ""
    try:
        # Cap at 3MB to avoid huge downloads
        async with session.get(txt_url, headers={"User-Agent": UA},
                               timeout=aiohttp.ClientTimeout(total=60)) as r:
            if r.status >= 400:
                return ""
            chunks = []
            total = 0
            async for chunk in r.content.iter_chunked(65536):
                chunks.append(chunk)
                total += len(chunk)
                if total > 3_000_000:
                    break
            text = b"".join(chunks).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    ! IA fetch error {item_id}: {e}", file=sys.stderr)
        return ""
    return extract_context(text)


# ---- Gallica BnF ----

async def extract_gallica(session, rec) -> str:
    """Use Gallica ContentSearch to find pages with regional terms, return excerpts."""
    sid = rec.get("source_id", "")
    if not sid:
        return ""
    ark = sid if sid.startswith("ark:") else f"ark:/12148/{sid}"
    # Try with primary anchor terms (avoids 0-result on niche full names)
    excerpts = []
    for term in ["Dulcigno", "Olcinium", "Ulcinj", "Bojana", "Scodra", "Antibarum"]:
        url = "https://gallica.bnf.fr/services/ContentSearch"
        params = {"ark": ark, "query": term}
        try:
            async with session.get(url, params=params, headers={"User-Agent": UA}) as r:
                if r.status >= 400:
                    continue
                xml = await r.text()
        except Exception:
            continue
        # Parse <item><content>...</content></item>
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
        for it in items[:3]:
            content_m = re.search(r"<content>(.*?)</content>", it, re.S)
            page_m = re.search(r"<p_pagination>(.*?)</p_pagination>", it, re.S)
            if content_m:
                content = re.sub(r"<[^>]+>", "", content_m.group(1)).strip()
                content = re.sub(r"\s+", " ", content)[:500]
                page = page_m.group(1).strip() if page_m else ""
                excerpts.append(f"[Strana {page}] …{content}…" if page else f"…{content}…")
        if len(excerpts) >= 5:
            break
    return "\n\n".join(excerpts[:5])


EXTRACTORS = {
    "internet_archive": extract_ia,
    "gallica": extract_gallica,
}


async def process_source(source: str):
    print(f"\n=== {source} ===", flush=True)
    records = fetch_records(source, limit=200)
    print(f"  {len(records)} records to process")
    if not records:
        return
    fn = EXTRACTORS[source]
    timeout = aiohttp.ClientTimeout(total=90)
    updated = 0
    skipped_empty = 0
    skipped_error = 0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, rec in enumerate(records):
            try:
                full_text = await fn(session, rec)
                if full_text and len(full_text) > 60:
                    patch_full_text(rec["id"], full_text)
                    updated += 1
                else:
                    skipped_empty += 1
            except Exception as e:
                skipped_error += 1
                if skipped_error <= 3:
                    print(f"  ! {rec.get('source_id')}: {e}")
            if (i + 1) % 10 == 0:
                print(f"  ... {i + 1}/{len(records)} ({updated} extracted)")
            # Rate limit
            await asyncio.sleep(0.3 if source == "gallica" else 0.5)
    print(f"  ✓ {source}: {updated} extracted, {skipped_empty} no-match, {skipped_error} errors")


async def main():
    print(f"Regional terms loaded: {len(ALL_TERMS)} variants")
    print(f"Sample: {ALL_TERMS[:8]}")
    for src in ["gallica", "internet_archive"]:
        try:
            await process_source(src)
        except Exception as e:
            print(f"  !! {src} failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
