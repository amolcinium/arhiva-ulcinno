import type { APIRoute } from 'astro';
import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.PUBLIC_SUPABASE_URL;

export const POST: APIRoute = async ({ request, locals }) => {
  const serviceKey = (locals as any)?.runtime?.env?.SUPABASE_SERVICE_KEY ?? process.env.SUPABASE_SERVICE_KEY;
  const adminToken = (locals as any)?.runtime?.env?.ADMIN_TOKEN ?? process.env.ADMIN_TOKEN;

  if (!serviceKey || !adminToken) {
    return new Response(JSON.stringify({ error: 'Service not configured' }), { status: 503 });
  }

  let body: { id?: string; token?: string; hide?: boolean; reason?: string };
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 400 });
  }

  if (body.token !== adminToken) {
    return new Response(JSON.stringify({ error: 'Forbidden' }), { status: 403 });
  }
  if (!body.id) {
    return new Response(JSON.stringify({ error: 'Missing id' }), { status: 400 });
  }

  const supa = createClient(SUPABASE_URL, serviceKey, { auth: { persistSession: false } });

  // Fetch current metadata
  const { data: rec, error: fetchErr } = await supa
    .from('archive_results')
    .select('metadata')
    .eq('id', body.id)
    .maybeSingle();
  if (fetchErr || !rec) {
    return new Response(JSON.stringify({ error: 'Record not found' }), { status: 404 });
  }

  const md = (rec.metadata as any) ?? {};
  const hide = body.hide !== false; // default true; pass {hide:false} to unhide
  if (hide) {
    md.hidden = true;
    md.hidden_at = new Date().toISOString();
    if (body.reason) md.hidden_reason = body.reason.slice(0, 200);
  } else {
    delete md.hidden;
    delete md.hidden_at;
    delete md.hidden_reason;
  }

  const { error: updErr } = await supa
    .from('archive_results')
    .update({ metadata: md })
    .eq('id', body.id);
  if (updErr) {
    return new Response(JSON.stringify({ error: updErr.message }), { status: 500 });
  }

  return new Response(JSON.stringify({ ok: true, hidden: hide }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
};

// Bulk hide endpoint: POST {token, ids: [...]}
export const PUT: APIRoute = async ({ request, locals }) => {
  const serviceKey = (locals as any)?.runtime?.env?.SUPABASE_SERVICE_KEY ?? process.env.SUPABASE_SERVICE_KEY;
  const adminToken = (locals as any)?.runtime?.env?.ADMIN_TOKEN ?? process.env.ADMIN_TOKEN;
  if (!serviceKey || !adminToken) {
    return new Response(JSON.stringify({ error: 'Service not configured' }), { status: 503 });
  }
  const body = await request.json().catch(() => ({}));
  if (body.token !== adminToken) return new Response(JSON.stringify({ error: 'Forbidden' }), { status: 403 });
  const ids: string[] = Array.isArray(body.ids) ? body.ids.slice(0, 1000) : [];
  if (!ids.length) return new Response(JSON.stringify({ error: 'No ids' }), { status: 400 });

  const supa = createClient(SUPABASE_URL, serviceKey, { auth: { persistSession: false } });
  const { data: recs } = await supa.from('archive_results').select('id, metadata').in('id', ids);
  let n = 0;
  for (const rec of recs ?? []) {
    const md = (rec.metadata as any) ?? {};
    md.hidden = true;
    md.hidden_at = new Date().toISOString();
    if (body.reason) md.hidden_reason = body.reason.slice(0, 200);
    await supa.from('archive_results').update({ metadata: md }).eq('id', rec.id);
    n++;
  }
  return new Response(JSON.stringify({ ok: true, hidden: n }), { status: 200 });
};
