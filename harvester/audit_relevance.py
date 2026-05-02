#!/usr/bin/env python3
"""
Relevance audit — auto-hide records that don't have a clear Ulcinj anchor.

Logic per record:
  - KEEP if location ∈ {ulcinj, stari_grad_ulcinj, stari_ulcinj_kruce, kruce, valdanos}
  - KEEP if title/snippet/full_text contains ANY anchor term:
      Ulcinj | Olcinium | Olchinium | Colchinium | Dulcigno | Dolcigno |
      Ulqin | Ulqini | Ülgün | Olgun | Ulcinium | Olcinj | Улцињ
  - KEEP if location ∈ {bar, stari_bar, antibar} AND has Ulcinj-region context
    (bar/skadar are valid related locations only when Ulcinj is also in text)
  - HIDE otherwise (set metadata.hidden = true with reason='relevance_audit')

Run:
  export SUPABASE_SERVICE_KEY="..."
  python3 audit_relevance.py             # dry-run, just report counts
  python3 audit_relevance.py --apply     # actually mark records hidden
  python3 audit_relevance.py --restore   # un-hide records previously auto-hidden by this script
"""
import argparse
import json
import os
import re
import sys
import urllib.request

SUPABASE_URL = "https://frsgzfzvdxswqjpdmcsd.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not SUPABASE_KEY:
    print("ERROR: set SUPABASE_SERVICE_KEY env var", file=sys.stderr)
    sys.exit(1)
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

# Locations that are SO specific to Ulcinj that we trust them automatically.
DIRECT_ULCINJ_LOCATIONS = {
    "ulcinj", "stari_grad_ulcinj", "stari_ulcinj_kruce",
    "kruce", "valdanos", "kalaja"
}

# Locations that are ulcinj-region but ALSO match unrelated content frequently.
# Records tagged with these locations need explicit Ulcinj anchor in text to qualify.
PROBLEMATIC_LOCATIONS = {
    "bojana_buna", "ada_bojana", "anamali", "kraja", "kufin", "agirana", "gjerana",
    "venetian_albania", "duklja_zeta", "skadarsko_jezero", "crmnica", "mrkovici"
}

# Ulcinj anchor terms — case-insensitive search in title+snippet+full_text.
ANCHOR_TERMS = [
    "Ulcinj", "Ulqin", "Olcinium", "Olchinium", "Olcynium", "Colchinium",
    "Dulcigno", "Dolcigno", "Dulcignum", "Ulcinium",
    "Ülgün", "Olgun",  # Ottoman
    "Олcинj", "Улцињ",  # Cyrillic Slavic
    "Ολκίνιον",  # Greek
    "Adriatic", "Adriatico", "Mletačka Albanija", "Albania Veneta",  # broader contextual
]
ANCHOR_RE = re.compile("|".join(re.escape(t) for t in ANCHOR_TERMS), re.IGNORECASE)


def fetch_all_records(limit_each: int = 1000) -> list[dict]:
    """Paginate through ALL non-hidden records to audit them."""
    all_recs = []
    offset = 0
    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/archive_results"
            f"?select=id,source,location,title,snippet,full_text,metadata"
            f"&or=(metadata->>hidden.is.null,metadata->>hidden.neq.true)"
            f"&order=id&limit={limit_each}&offset={offset}"
        )
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            batch = json.load(r)
        if not batch:
            break
        all_recs.extend(batch)
        if len(batch) < limit_each:
            break
        offset += limit_each
    return all_recs


def has_anchor_term(rec: dict) -> bool:
    """True if title, snippet, or full_text contains an Ulcinj anchor term."""
    blob = " ".join([
        str(rec.get("title") or ""),
        str(rec.get("snippet") or ""),
        str(rec.get("full_text") or ""),
    ])
    return bool(ANCHOR_RE.search(blob))


def classify(rec: dict) -> str:
    """Return one of: 'keep', 'suspect'."""
    loc = rec.get("location") or ""
    if loc in DIRECT_ULCINJ_LOCATIONS:
        return "keep"
    # For problematic and other locations: require anchor term in text
    if has_anchor_term(rec):
        return "keep"
    return "suspect"


def patch_hidden(rid: str, hide: bool, reason: str = ""):
    """Set or clear metadata.hidden + hidden_reason."""
    # Fetch current metadata
    url = f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}&select=metadata"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if not data:
        return
    md = data[0].get("metadata") or {}
    if hide:
        md["hidden"] = True
        md["hidden_at"] = "2026-05-02T08:00:00Z"
        md["hidden_reason"] = reason or "relevance_audit"
    else:
        md.pop("hidden", None)
        md.pop("hidden_at", None)
        md.pop("hidden_reason", None)
    body = json.dumps({"metadata": md}).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/archive_results?id=eq.{rid}",
        data=body, method="PATCH",
        headers={**HEADERS, "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually mark suspect records hidden")
    ap.add_argument("--restore", action="store_true", help="Un-hide records previously hidden by this script")
    args = ap.parse_args()

    if args.restore:
        # Find records hidden by this audit
        url = (
            f"{SUPABASE_URL}/rest/v1/archive_results"
            f"?metadata->>hidden_reason=eq.relevance_audit"
            f"&select=id&limit=2000"
        )
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            recs = json.load(r)
        print(f"Found {len(recs)} records hidden by audit. Restoring...")
        for i, rec in enumerate(recs):
            patch_hidden(rec["id"], hide=False)
            if (i + 1) % 50 == 0:
                print(f"  ... {i + 1}/{len(recs)}")
        print(f"✓ Restored {len(recs)} records.")
        return

    print("Fetching all visible records...", file=sys.stderr)
    recs = fetch_all_records()
    print(f"Total visible: {len(recs)}", file=sys.stderr)

    keep = []
    suspect = []
    by_source_suspect = {}
    by_location_suspect = {}

    for rec in recs:
        c = classify(rec)
        if c == "keep":
            keep.append(rec)
        else:
            suspect.append(rec)
            src = rec.get("source") or "?"
            by_source_suspect[src] = by_source_suspect.get(src, 0) + 1
            loc = rec.get("location") or "(no location)"
            by_location_suspect[loc] = by_location_suspect.get(loc, 0) + 1

    print(f"\n=== AUDIT REPORT ===")
    print(f"Keep:    {len(keep):4d}  ({100*len(keep)/len(recs):5.1f}%)")
    print(f"Suspect: {len(suspect):4d}  ({100*len(suspect)/len(recs):5.1f}%)")

    print(f"\nSuspects by source:")
    for src, n in sorted(by_source_suspect.items(), key=lambda x: -x[1]):
        print(f"  {src:20s} {n:4d}")

    print(f"\nSuspects by location:")
    for loc, n in sorted(by_location_suspect.items(), key=lambda x: -x[1]):
        print(f"  {loc:30s} {n:4d}")

    if not args.apply:
        print(f"\n[DRY RUN] No changes made. Run with --apply to hide {len(suspect)} suspect records.")
        print(f"To restore later: python3 audit_relevance.py --restore")
        return

    # Apply: hide all suspects
    print(f"\nApplying — hiding {len(suspect)} suspect records...")
    for i, rec in enumerate(suspect):
        try:
            patch_hidden(rec["id"], hide=True, reason="relevance_audit")
        except Exception as e:
            print(f"  ! {rec['id']}: {e}")
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(suspect)}")
    print(f"✓ Hidden {len(suspect)} records. Use /admin/sakriveni to review or audit_relevance.py --restore to bulk-undo.")


if __name__ == "__main__":
    main()
