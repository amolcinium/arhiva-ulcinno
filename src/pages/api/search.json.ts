import type { APIRoute } from 'astro';
import { searchResults } from '../../lib/supabase';

export const GET: APIRoute = async ({ url }) => {
  const params = url.searchParams;
  try {
    const out = await searchResults({
      q: params.get('q') ?? undefined,
      location: params.get('location') ?? undefined,
      source: params.get('source') ?? undefined,
      yearMin: params.get('yearMin') ? parseInt(params.get('yearMin')!) : undefined,
      yearMax: params.get('yearMax') ? parseInt(params.get('yearMax')!) : undefined,
      limit: Math.min(parseInt(params.get('limit') ?? '30'), 100),
      offset: parseInt(params.get('offset') ?? '0'),
    });
    return new Response(JSON.stringify(out), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e.message ?? 'unknown' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
