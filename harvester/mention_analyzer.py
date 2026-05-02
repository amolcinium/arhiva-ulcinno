#!/usr/bin/env python3
"""
Mention analyzer — for each record with full_text or where we can fetch it,
build a structured mention map: count, page numbers, context per occurrence,
auto-detected topic.

Stores result in metadata.mentions JSONB:
{
  "total": 7,
  "by_term": {"Olcinium": 3, "Dulcigno": 4},
  "by_page": [
    {"page": 12, "count": 2, "extracts": ["..."], "topics": ["trade"]},
    {"page": 47, "count": 1, "extracts": ["..."], "topics": ["military"]}
  ],
  "topics_summary": {"trade": 4, "military": 2, "religious": 1},
  "analyzed_at": "2026-05-02T..."
}

Run:
  export SUPABASE_SERVICE_KEY="..."
  python3 mention_analyzer.py             # process all records with full_text
  python3 mention_analyzer.py --refetch   # re-fetch source djvu.txt for IA records that don't yet have full_text
"""
import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import aiohttp

SUPABASE_URL = "https://frsgzfzvdxswqjpdmcsd.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not SUPABASE_KEY:
    print("ERROR: set SUPABASE_SERVICE_KEY", file=sys.stderr)
    sys.exit(1)
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
UA = "arhiva-ulcinno-mention-analyzer/1.0"

# Anchor terms — same as audit, what counts as "mention"
ANCHOR_TERMS = [
    "Ulcinj", "Ulqin", "Ulqini", "Ulqinaku",
    "Olcinium", "Olchinium", "Olcynium", "Colchinium", "Olcinia", "Olcinj",
    "Vicinium", "Lucinium", "Ulcinium",
    "Dulcigno", "Dolcigno", "Dulcignum", "Dulcinium", "Dulcignano", "Dulcinj",
    "Ülgün", "Olgun", "Ülkün",
    "Улцињ", "Улцин", "Ольцин",
    "Ολκίνιον", "Ολχίνιον", "Δουλκίνιον",
    "Ulciniates", "Olcinitanus",
]
TERM_PATTERN = re.compile("|".join(re.escape(t) for t in ANCHOR_TERMS), re.IGNORECASE)

# Topic detection — keywords that strongly indicate a theme around the mention
TOPIC_KEYWORDS = {
    "trade": ["trade", "trgovina", "trgovin", "merchant", "trgovc", "salt", "sale", "saline", "solan", "solana",
              "olive", "maslin", "wine", "vino", "amphora", "port", "luka", "harbor", "import", "export",
              "commerce", "merc", "vino", "ulje", "dukat", "ducat", "florin", "gold"],
    "military": ["siege", "opsad", "battle", "bitka", "fortress", "fortezza", "tvrđav", "castle", "kaštel",
                 "war", "rat", "military", "vojsk", "army", "soldier", "vojnik", "naval", "ratni brod",
                 "galiot", "brigantin", "fusta", "pirate", "gusar", "corsair", "captain", "kapetan",
                 "lance", "sword", "cannon", "top", "oružje"],
    "religious": ["bishop", "biskup", "diocese", "diocez", "cathedral", "katedrala", "church", "crkva",
                  "pope", "papa", "monastery", "manastir", "abbey", "saint", "sveti", "altar",
                  "archbishop", "nadbiskup", "ecclesiast", "religious", "religijsk", "patron",
                  "patriarchate", "patrijarhat", "orthodox", "pravoslav", "catholic", "katolik",
                  "muslim", "musliman", "islam"],
    "cartographic": ["map", "karta", "carta", "mappa", "tabula", "chart", "atlas", "draw", "engrav",
                     "gravur", "isolario", "portolano", "chart", "geograf", "cartograph"],
    "civil": ["citizen", "građan", "council", "vijeće", "podestà", "rector", "rektor", "captain",
              "captain", "noble", "plemić", "patrician", "patricij", "court", "sud", "tribunal",
              "law", "zakon", "decree", "dekret", "statute", "statut", "census", "popis"],
    "diplomatic": ["ambassador", "ambasador", "treaty", "ugovor", "embassy", "delegation", "delegacij",
                   "diplomat", "negotiat", "pregovor", "alliance", "savez", "letter", "pismo"],
    "demographic": ["population", "stanovništv", "ethnic", "etničk", "language", "jezik", "albanian",
                    "albansk", "slav", "slavic", "vlach", "vlah", "turk", "turčin", "morlach",
                    "morlak", "settler", "naselj"],
}


def fetch_records_with_text(limit: int = 5000) -> list[dict]:
    """Fetch all records that have non-empty full_text (worth analyzing)."""
    url = (
        f"{SUPABASE_URL}/rest/v1/archive_results"
        f"?select=id,source,source_id,title,full_text,metadata"
        f"&full_text=not.is.null&full_text=neq."
        f"&limit={limit}"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def detect_topics(snippet: str) -> list[str]:
    """Detect topic tags from a context snippet."""
    text = snippet.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(topic)
    return found


def split_into_pages(full_text: str) -> list[str]:
    """Split OCR text by form-feed (djvu page break). Returns one-string-per-page."""
    if "\f" in full_text:
        return full_text.split("\f")
    # Fallback: estimate pages by char count (~3000 chars per page)
    PAGE_CHARS = 3000
    return [full_text[i:i + PAGE_CHARS] for i in range(0, len(full_text), PAGE_CHARS)]


def analyze_text(full_text: str) -> dict:
    """Build structured mention map from full text."""
    pages = split_into_pages(full_text)
    by_page = []
    by_term: Counter = Counter()
    topics_summary: Counter = Counter()

    for page_num, page_text in enumerate(pages, 1):
        matches = list(TERM_PATTERN.finditer(page_text))
        if not matches:
            continue
        # Build per-page summary
        extracts = []
        page_topics = set()
        for m in matches[:5]:  # cap 5 extracts per page
            term = m.group(0)
            by_term[term.lower()] += 1
            start = max(0, m.start() - 150)
            end = min(len(page_text), m.end() + 150)
            ctx = page_text[start:end].strip()
            ctx = re.sub(r"\s+", " ", ctx)
            ctx = ctx.replace("- ", "")  # OCR line-break hyphens
            extracts.append(f"…{ctx}…")
            for t in detect_topics(ctx):
                page_topics.add(t)
        for t in page_topics:
            topics_summary[t] += 1
        by_page.append({
            "page": page_num,
            "count": len(matches),
            "extracts": extracts,
            "topics": sorted(page_topics),
        })

    total = sum(by_term.values())
    return {
        "total": total,
        "by_term": dict(by_term),
        "by_page": by_page,
        "topics_summary": dict(topics_summary),
        "analyzed_at": "2026-05-02T09:30:00Z",
    }


def patch_mentions(rid: str, mentions: dict, existing_md: dict):
    """Update record's metadata.mentions field."""
    md = dict(existing_md)
    md["mentions"] = mentions
    body = json.dumps({"metadata": md}).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}",
        data=body, method="PATCH",
        headers={**HEADERS, "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true",
                    help="Also refetch IA djvu.txt for records without full_text yet")
    args = ap.parse_args()

    print("Fetching records with full_text...", file=sys.stderr)
    recs = fetch_records_with_text()
    print(f"  Found {len(recs)} records with full_text\n", file=sys.stderr)

    n_analyzed = 0
    n_skipped = 0
    by_topic = Counter()
    for i, rec in enumerate(recs):
        ft = rec.get("full_text") or ""
        if len(ft) < 200:
            n_skipped += 1
            continue
        try:
            mentions = analyze_text(ft)
            if mentions["total"] == 0:
                # No anchor terms found — skip (audit should have caught this)
                n_skipped += 1
                continue
            existing_md = rec.get("metadata") or {}
            patch_mentions(rec["id"], mentions, existing_md)
            n_analyzed += 1
            for t, n in mentions["topics_summary"].items():
                by_topic[t] += n
            if (i + 1) % 25 == 0:
                print(f"  ... {i + 1}/{len(recs)} ({n_analyzed} analyzed)", file=sys.stderr)
        except Exception as e:
            print(f"  ! {rec['id']}: {e}", file=sys.stderr)
            n_skipped += 1

    print(f"\n=== ANALYSIS COMPLETE ===")
    print(f"Analyzed: {n_analyzed}, Skipped: {n_skipped}")
    if by_topic:
        print(f"\nMost common topics across all docs:")
        for topic, n in by_topic.most_common():
            print(f"  {topic:14s} {n} document-pages")


if __name__ == "__main__":
    main()
