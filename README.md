# Arhiva Ulcinj — `arhiva.ulcinno.com`

Federalni search portal za stare arhivske izvore o Ulcinju i okolini.
Astro + Tailwind + Supabase, hostovano na Cloudflare Pages.

## Status

- 15 lokacija u rječniku, 577 stavki harvestovano (Europeana + Internet Archive + EDH dump)
- Pretraga ide preko Supabase view-a `archive_results_public` (read-only)
- Skill koji puni bazu: `~/.claude/skills/archive-search/`

## Setup (jednom)

1. **Apply Supabase migraciju.** U Supabase Studio → SQL Editor, paste sadržaj `~/.claude/skills/archive-search/migration.sql` i klik Run.

2. **Instaliraj deps:**
   ```bash
   cd /mnt/c/PlatformWeb/arhiva-ulcinno
   npm install
   ```

3. **Postavi env:**
   ```bash
   cp .env.example .env
   # Otvori .env, paste anon key sa Supabase Studio → Project Settings → API
   ```

4. **Pokreni dev server:**
   ```bash
   npm run dev
   ```
   Otvori http://localhost:4321

5. **Push to GitHub i poveži CF Pages:**
   ```bash
   git init && git add . && git commit -m "initial: arhiva.ulcinno.com scaffold"
   gh repo create maverick-sea/arhiva-ulcinno --public --source=. --push
   ```
   U Cloudflare Pages → Create project → connect GitHub repo → set build cmd `npm run build` → output `dist` → env vars: `PUBLIC_SUPABASE_URL`, `PUBLIC_SUPABASE_ANON_KEY` → Custom domain: `arhiva.ulcinno.com`.

## Punjenje baze (svaki put kad hoćeš svježe podatke)

```bash
cd ~/.claude/skills/archive-search
export SUPABASE_SERVICE_KEY="<service role key sa Supabase>"
python3 search.py --harvest --limit 50 --upload
```

Ovo prolazi kroz svih 15 primarnih lokacija, hita 3 izvora paralelno, i upisuje u `archive_results` (sa dedupe-om).

## Kako dodaš novu lokaciju

1. Edituj `~/.claude/skills/archive-search/regional-vocab.json` — dodaj novu stavku u `primary_locations` ili `regional_locations` sa `modern` i `historical` varijantama
2. Dodaj u `LOCATIONS` array u `src/lib/supabase.ts` da se pojavi u UI-u
3. Pokreni harvest da popuni bazu

## Tech stack

- Astro 4 (SSR via Cloudflare adapter)
- Tailwind CSS
- Supabase JS klijent (read-only sa anon key, RLS)
- Custom palette: parchment + venetian + ottoman + gold (knjiški izgled)
- Serif: EB Garamond | Sans: Inter

## Backlog

- Tier 2 connectors: Manus Online, Biblissima, Pelagios, Trismegistos, DACG (CG)
- Playwright fallback za DigiVatLib + Antenati (zaobići 403 bot-protection)
- IIIF Mirador viewer integration za zoom
- Map view sa EDH koordinatama (Leaflet)
- Bookmark/favorites za prijavljene korisnike
- Daily cron: re-harvest top lokacija
