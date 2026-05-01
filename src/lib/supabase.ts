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
  digivatlib: 'DigiVatLib (Vatikan)',
  antenati: 'Antenati (Italija)',
  edr: 'EDR (Roma)',
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

export async function searchResults(opts: {
  q?: string;
  location?: string;
  source?: string;
  yearMin?: number;
  yearMax?: number;
  limit?: number;
  offset?: number;
}) {
  const { q, location, source, yearMin, yearMax, limit = 30, offset = 0 } = opts;
  let query = supabase.from('archive_results_public').select('*', { count: 'exact' });
  if (q) {
    query = query.or(`title.ilike.%${q}%,snippet.ilike.%${q}%,author.ilike.%${q}%`);
  }
  if (location) query = query.contains('tags', [location]);
  if (source) query = query.eq('source', source);
  if (yearMin) query = query.gte('date_year_min', yearMin);
  if (yearMax) query = query.lte('date_year_max', yearMax);
  query = query.order('date_year_min', { ascending: true, nullsFirst: false }).range(offset, offset + limit - 1);
  const { data, count, error } = await query;
  if (error) throw error;
  return { results: (data ?? []) as ArchiveResult[], total: count ?? 0 };
}
