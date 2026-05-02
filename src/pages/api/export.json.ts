import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import { COLLECTIONS_BY_SLUG } from '../../lib/collections';

export const GET: APIRoute = async ({ url }) => {
  const params = url.searchParams;
  const colSlug = params.get('collection');
  const q = params.get('q');
  const location = params.get('location');
  const source = params.get('source');

  let query = supabase.from('archive_results_public').select('*');

  if (colSlug) {
    const col = COLLECTIONS_BY_SLUG[colSlug];
    if (!col) return new Response('Unknown collection', { status: 404 });
    if (col.filter.sources?.length) query = query.in('source', col.filter.sources);
    if (col.filter.locations?.length) query = query.in('location', col.filter.locations);
    if (col.filter.yearMin !== undefined) query = query.gte('date_year_min', col.filter.yearMin);
    if (col.filter.yearMax !== undefined) query = query.lte('date_year_max', col.filter.yearMax);
    if (col.filter.qLike?.length) {
      const ors = col.filter.qLike.flatMap((p) => [`title.ilike.%${p}%`, `snippet.ilike.%${p}%`]).join(',');
      query = query.or(ors);
    }
  } else {
    if (q) query = query.or(`title.ilike.%${q}%,snippet.ilike.%${q}%,author.ilike.%${q}%`);
    if (location) query = query.contains('tags', [location]);
    if (source) query = query.eq('source', source);
  }

  query = query.order('date_year_min', { ascending: true, nullsFirst: false }).limit(2000);

  const { data, error } = await query;
  if (error) return new Response(JSON.stringify({ error: error.message }), { status: 500, headers: { 'Content-Type': 'application/json' } });

  const filename = colSlug ? `arhiva-ulcinno-${colSlug}.json` : 'arhiva-ulcinno-export.json';
  return new Response(JSON.stringify(data ?? [], null, 2), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Disposition': `attachment; filename="${filename}"`,
    },
  });
};
