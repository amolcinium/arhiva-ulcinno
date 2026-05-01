# Archive Harvester

Standalone copy of the archive-search Python script for GitHub Actions execution.

## Files

- `search.py` — main async harvester (mirror of `~/.claude/skills/archive-search/search.py`)
- `regional-vocab.json` — 27 lokacija multi-name dictionary
- `data/edh-geo.json` — fetched fresh from GitHub mirror at each Action run

## Manual run

```bash
cd harvester
mkdir -p data
curl -sSL -o data/edh-geo.json https://raw.githubusercontent.com/epigraphic-database-heidelberg/data/master/geography/edhGeographicData.json
pip install aiohttp
export SUPABASE_SERVICE_KEY="<service key>"
python3 search.py --harvest --limit 50 --upload \
  --source europeana --source internet_archive --source edh \
  --source pelagios --source wikidata
```

## GitHub Actions schedule

Weekly Monday 04:17 UTC. See `.github/workflows/harvest.yml`.
Manual trigger via Actions tab → "Weekly Archive Harvest" → "Run workflow".

## Required GitHub secret

`SUPABASE_SERVICE_KEY` — set under repo Settings → Secrets and variables → Actions → New repository secret.

## Sync from skill

When the local skill is updated, sync these files:
```bash
cp ~/.claude/skills/archive-search/search.py harvester/
cp ~/.claude/skills/archive-search/regional-vocab.json harvester/
git commit -m "sync: harvester from local skill"
```

The EDH dump is NOT committed — fetched at runtime to stay fresh.
