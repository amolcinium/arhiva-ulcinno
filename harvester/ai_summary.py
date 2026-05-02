#!/usr/bin/env python3
"""
AI summary — for each record with full_text + mentions analysis,
ask Claude Haiku to generate 2-3 sentence summary in CG explaining
WHY the document is relevant to Ulcinj research.

Stores result in metadata.ai_summary.

Run:
  export SUPABASE_SERVICE_KEY="..."
  export ANTHROPIC_API_KEY="..."
  python3 ai_summary.py             # process all records with mentions but no ai_summary
  python3 ai_summary.py --limit 50  # cap per run (default unlimited)
"""
import argparse
import json
import os
import re
import sys
import urllib.request

SUPABASE_URL = "https://frsgzfzvdxswqjpdmcsd.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not SUPABASE_KEY or not ANTHROPIC_KEY:
    print("ERROR: set SUPABASE_SERVICE_KEY and ANTHROPIC_API_KEY", file=sys.stderr)
    sys.exit(1)

HEADERS_SUPA = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}


def fetch_records(limit: int = 5000) -> list[dict]:
    """Fetch records that have mentions but no ai_summary yet."""
    url = (
        f"{SUPABASE_URL}/rest/v1/archive_results"
        f"?select=id,source,title,author,date_text,location,full_text,metadata"
        f"&metadata->mentions=not.is.null"
        f"&limit={limit}"
    )
    req = urllib.request.Request(url, headers=HEADERS_SUPA)
    with urllib.request.urlopen(req) as r:
        recs = json.load(r)
    # Client-side filter: no ai_summary yet
    return [r for r in recs if not (r.get("metadata") or {}).get("ai_summary")]


def call_claude(prompt: str) -> str:
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body, method="POST",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return data.get("content", [{}])[0].get("text", "")


def patch_summary(rid: str, summary: str, existing_md: dict):
    md = dict(existing_md)
    md["ai_summary"] = summary
    md["ai_summary_at"] = "2026-05-02T12:00:00Z"
    body = json.dumps({"metadata": md}).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}",
        data=body, method="PATCH",
        headers={**HEADERS_SUPA, "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req)


def build_prompt(rec: dict) -> str:
    md = rec.get("metadata") or {}
    mentions = md.get("mentions") or {}
    extracts = []
    for p in mentions.get("by_page", [])[:5]:
        for ex in p.get("extracts", [])[:2]:
            extracts.append(f"[Strana {p['page']}] {ex}")
    topics = list((mentions.get("topics_summary") or {}).keys())
    return f"""Ti si stručnjak za istoriju Ulcinja. Na osnovu sledećih informacija o dokumentu, napiši **2-3 rečenice na crnogorskom (latinica)** koje objašnjavaju ZAŠTO je ovaj dokument relevantan za istraživanje Ulcinja.

Dokument:
- Naslov: {rec.get('title','')[:200]}
- Autor: {rec.get('author','') or 'nepoznat'}
- Datum: {rec.get('date_text','') or 'nepoznat'}
- Lokacija: {rec.get('location','') or 'nepoznata'}
- Pominje Ulcinj {mentions.get('total', 0)} puta na {len(mentions.get('by_page', []))} strana
- Glavne teme: {', '.join(topics) or 'nepoznato'}

Izvodi konteksta gdje se Ulcinj pominje:
{chr(10).join(extracts[:8])}

Tvoj zadatak: 2-3 sažete rečenice na CG koje govore:
1. Šta je dokument (knjiga/članak/karta/itd.)
2. Kako se odnosi na Ulcinj (period, kontekst, tema)
3. Zašto je vrijedan za istraživača

NE počinji sa "Ovaj dokument..." ili sličnim opštim formulacijama. Direktno opiši sadržaj."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Cap records per run")
    args = ap.parse_args()

    print("Fetching records with mentions but no ai_summary...", file=sys.stderr)
    recs = fetch_records()
    if args.limit:
        recs = recs[:args.limit]
    print(f"  Found {len(recs)} records to summarize\n", file=sys.stderr)

    n_done = 0
    n_skip = 0
    for i, rec in enumerate(recs):
        try:
            prompt = build_prompt(rec)
            summary = call_claude(prompt).strip()
            if len(summary) > 30:
                patch_summary(rec["id"], summary, rec.get("metadata") or {})
                n_done += 1
            else:
                n_skip += 1
        except Exception as e:
            print(f"  ! {rec['id']}: {e}", file=sys.stderr)
            n_skip += 1
        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(recs)} ({n_done} summarized)", file=sys.stderr)

    print(f"\n=== AI SUMMARY COMPLETE ===")
    print(f"Summarized: {n_done}, Skipped: {n_skip}")
    print(f"Approx cost: ${n_done * 0.005:.2f} (Haiku at ~$0.005/call)")


if __name__ == "__main__":
    main()
