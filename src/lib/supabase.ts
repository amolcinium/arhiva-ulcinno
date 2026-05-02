import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.PUBLIC_SUPABASE_URL;
const key = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

export const supabase = createClient(url, key, {
  auth: { persistSession: false },
});

export interface ArchiveResult {
  id: string;
  source: string;
  source_id: string | null;
  title: string;
  author: string | null;
  date_text: string | null;
  date_year_min: number | null;
  date_year_max: number | null;
  location: string | null;
  language: string | null;
  doc_type: string | null;
  url_original: string;
  url_iiif: string | null;
  thumbnail_url: string | null;
  snippet: string | null;
  tags: string[];
  fetched_at: string;
}

export const SOURCE_LABELS: Record<string, string> = {
  europeana: 'Europeana',
  internet_archive: 'Internet Archive',
  edh: 'EDH (rimski natpisi)',
  pelagios: 'Pelagios (antičke lokacije)',
  wikidata: 'Wikidata',
  gallica: 'BnF Gallica (Francuska)',
  loc: 'Library of Congress (SAD)',
  wellcome: 'Wellcome Collection (UK)',
  crossref: 'CrossRef (akademski radovi)',
  openlibrary: 'Open Library',
  nb_no: 'Norwegian National Library',
  smithsonian: 'Smithsonian',
  openaire: 'OpenAIRE (EU akademski)',
  openalex: 'OpenAlex (scholarly graph)',
  doaj: 'DOAJ (open access journals)',
  zenodo: 'Zenodo (CERN repozitorij)',
  core: 'CORE.ac.uk (akademski agregator)',
  rumsey: 'David Rumsey (istorijske karte)',
  ape: 'Archives Portal Europe',
  digivatlib: 'DigiVatLib (Vatikan)',
  antenati: 'Antenati (Italija)',
  edr: 'EDR (Roma)',
  bsb: 'Bayerische Staatsbibliothek (München)',
  slub: 'SLUB Dresden',
  manus: 'Manus Online (ICCU, talijanski rukopisi)',
  hathitrust: 'HathiTrust Digital Library',
  anno: 'ÖNB ANNO (austrijske novine)',
};

/**
 * Country/institution origin per source. Shown on result cards as flag + label.
 * Helps user quickly spot which national archive a record comes from.
 */
export const SOURCE_COUNTRIES: Record<string, { flag: string; country: string }> = {
  openaire:         { flag: '🇪🇺', country: 'EU akademski (OpenAIRE)' },
  openalex:         { flag: '🌍', country: 'Internacionalni (OpenAlex)' },
  doaj:             { flag: '🇬🇧', country: 'Velika Britanija (DOAJ)' },
  zenodo:           { flag: '🇨🇭', country: 'CERN/Švajcarska (Zenodo)' },
  core:             { flag: '🇬🇧', country: 'Velika Britanija (CORE)' },
  rumsey:           { flag: '🇺🇸', country: 'SAD (David Rumsey karte)' },
  ape:              { flag: '🇪🇺', country: 'Archives Portal Europe' },
  europeana:        { flag: '🇪🇺', country: 'EU agregator' },
  internet_archive: { flag: '🇺🇸', country: 'SAD' },
  edh:              { flag: '🇩🇪', country: 'Njemačka (Heidelberg)' },
  pelagios:         { flag: '🌍', country: 'Internacionalni' },
  wikidata:         { flag: '🌍', country: 'Internacionalni' },
  gallica:          { flag: '🇫🇷', country: 'Francuska' },
  loc:              { flag: '🇺🇸', country: 'SAD (Library of Congress)' },
  wellcome:         { flag: '🇬🇧', country: 'Velika Britanija' },
  crossref:         { flag: '🌍', country: 'Internacionalni (akademski)' },
  openlibrary:      { flag: '🇺🇸', country: 'SAD' },
  nb_no:            { flag: '🇳🇴', country: 'Norveška' },
  smithsonian:      { flag: '🇺🇸', country: 'SAD (Smithsonian)' },
  digivatlib:       { flag: '🇻🇦', country: 'Vatikan' },
  antenati:         { flag: '🇮🇹', country: 'Italija' },
  edr:              { flag: '🇮🇹', country: 'Italija (Roma)' },
  bsb:              { flag: '🇩🇪', country: 'Njemačka (München)' },
  slub:             { flag: '🇩🇪', country: 'Njemačka (Dresden)' },
  manus:            { flag: '🇮🇹', country: 'Italija (ICCU rukopisi)' },
  hathitrust:       { flag: '🇺🇸', country: 'SAD (akademska)' },
  anno:             { flag: '🇦🇹', country: 'Austrija (novine)' },
};

export const LOCATIONS = [
  { key: 'ulcinj',                 label: 'Ulcinj / Olcinium / Dulcigno' },
  { key: 'stari_grad_ulcinj',      label: 'Kalaja (Stari grad)' },
  { key: 'stari_ulcinj_kruce',     label: 'Stari Ulcinj kod Kruča (Dulcigno Vecchio)' },
  { key: 'kruce',                  label: 'Kruče' },
  { key: 'valdanos',               label: 'Valdanos / Val da noce' },
  { key: 'bojana_buna',            label: 'Bojana / Buna / Barbana' },
  { key: 'bar',                    label: 'Bar / Antibarum' },
  { key: 'skadar',                 label: 'Skadar / Scodra' },
  { key: 'svac',                   label: 'Svač / Suacium' },
  { key: 'drivast',                label: 'Drivast / Drivastum' },
  { key: 'anamali',                label: 'Anamali' },
  { key: 'kraja',                  label: 'Krajë (Skadarska Krajina)' },
  { key: 'venetian_albania',       label: 'Mletačka Albanija' },
];

export interface MapPoint {
  id: string;
  source: string;
  title: string;
  location: string | null;
  url_original: string;
  longitude: number;
  latitude: number;
  date_text: string | null;
  date_year_min: number | null;
}

function parseWktPoint(wkt: string): [number, number] | null {
  const m = wkt.match(/Point\s*\(\s*([+-]?\d+\.?\d*)\s+([+-]?\d+\.?\d*)\s*\)/i);
  if (!m) return null;
  const lng = parseFloat(m[1]);
  const lat = parseFloat(m[2]);
  if (isNaN(lng) || isNaN(lat)) return null;
  return [lng, lat];
}

export async function getMapPoints(): Promise<MapPoint[]> {
  // Fetch EDH (lat/lng in metadata), Wikidata (coord_wkt in metadata), and Pelagios
  const { data, error } = await supabase
    .from('archive_results')
    .select('id, source, title, location, url_original, date_text, date_year_min, metadata')
    .in('source', ['edh', 'wikidata', 'pelagios'])
    .limit(1000);
  if (error) {
    console.error('getMapPoints error', error);
    return [];
  }
  return (data ?? [])
    .map((r: any): MapPoint | null => {
      let lng: number | null = null;
      let lat: number | null = null;
      if (r.source === 'edh') {
        lng = typeof r.metadata?.longitude === 'number' ? r.metadata.longitude : null;
        lat = typeof r.metadata?.latitude === 'number' ? r.metadata.latitude : null;
      } else if (r.source === 'wikidata') {
        const wkt = r.metadata?.coord_wkt;
        if (wkt) {
          const coords = parseWktPoint(wkt);
          if (coords) { lng = coords[0]; lat = coords[1]; }
        }
      }
      // Pelagios records don't currently store coordinates — skip
      if (lng === null || lat === null) return null;
      return {
        id: r.id,
        source: r.source,
        title: r.title,
        location: r.location,
        url_original: r.url_original,
        longitude: lng,
        latitude: lat,
        date_text: r.date_text,
        date_year_min: r.date_year_min ?? null,
      };
    })
    .filter((x): x is MapPoint => x !== null);
}

export async function getItem(id: string): Promise<ArchiveResult | null> {
  const { data, error } = await supabase
    .from('archive_results')
    .select('id, source, source_id, title, author, date_text, date_year_min, date_year_max, location, language, doc_type, url_original, url_iiif, thumbnail_url, snippet, full_text, tags, fetched_at, metadata, relevance')
    .eq('id', id)
    .maybeSingle();
  if (error || !data) return null;
  return data as any;
}

export async function getRelated(item: ArchiveResult, limit = 6): Promise<ArchiveResult[]> {
  const out: ArchiveResult[] = [];
  // Strategy: same location first, then same source
  if (item.location) {
    const { data } = await supabase
      .from('archive_results_public')
      .select('*')
      .eq('location', item.location)
      .neq('id', item.id)
      .limit(limit);
    if (data) out.push(...(data as any[]));
  }
  if (out.length < limit) {
    const { data } = await supabase
      .from('archive_results_public')
      .select('*')
      .eq('source', item.source)
      .neq('id', item.id)
      .not('id', 'in', `(${out.map(r => `"${r.id}"`).join(',') || '""'})`)
      .limit(limit - out.length);
    if (data) out.push(...(data as any[]));
  }
  return out.slice(0, limit);
}

/**
 * Filter out records marked as hidden via metadata.hidden=true.
 * Reusable for any query — chains as additional .neq() / .or() condition.
 */
function applyHiddenFilter<T extends ReturnType<typeof supabase.from>>(query: T): T {
  // Postgres JSONB: metadata->>'hidden' returns text 'true' or null
  // We want records where it is NOT 'true' (so includes null + 'false')
  return (query as any).or('metadata->>hidden.is.null,metadata->>hidden.neq.true');
}

export async function searchResults(opts: {
  q?: string;
  location?: string;
  source?: string;
  yearMin?: number;
  yearMax?: number;
  language?: string;
  hasIiif?: boolean;
  topic?: string;
  limit?: number;
  offset?: number;
}) {
  const { q, location, source, yearMin, yearMax, language, hasIiif, limit = 30, offset = 0 } = opts;
  // Use base table (not view) so we can filter on metadata->>'hidden'
  let query = supabase.from('archive_results').select(
    'id, source, source_id, title, author, date_text, date_year_min, date_year_max, location, language, doc_type, url_original, url_iiif, thumbnail_url, snippet, tags, fetched_at',
    { count: 'exact' }
  );
  // Hidden filter: skip records where metadata.hidden is true
  query = (query as any).or('metadata->>hidden.is.null,metadata->>hidden.neq.true');
  if (q) {
    query = query.or(`title.ilike.%${q}%,snippet.ilike.%${q}%,author.ilike.%${q}%`);
  }
  if (location) query = query.contains('tags', [location]);
  if (source) query = query.eq('source', source);
  if (yearMin !== undefined) query = query.gte('date_year_min', yearMin);
  if (yearMax !== undefined) query = query.lte('date_year_max', yearMax);
  if (language) query = query.ilike('language', `%${language}%`);
  if (hasIiif) query = query.not('url_iiif', 'is', null);
  // Filter records where mentions has the requested topic (e.g., 'trade', 'military')
  if (opts.topic) query = (query as any).filter('metadata->mentions->topics_summary', 'cs', `{"${opts.topic}":1}`);
  query = query.order('date_year_min', { ascending: true, nullsFirst: false }).range(offset, offset + limit - 1);
  const { data, count, error } = await query;
  if (error) throw error;
  return { results: (data ?? []) as ArchiveResult[], total: count ?? 0 };
}
