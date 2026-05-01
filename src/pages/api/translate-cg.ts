import type { APIRoute } from 'astro';
import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.PUBLIC_SUPABASE_URL;

export const POST: APIRoute = async ({ request, locals }) => {
  // Use service role key from CF Pages env (server-side only, never exposed)
  const serviceKey = (locals as any)?.runtime?.env?.SUPABASE_SERVICE_KEY ?? process.env.SUPABASE_SERVICE_KEY;
  const anthropicKey = (locals as any)?.runtime?.env?.ANTHROPIC_API_KEY ?? process.env.ANTHROPIC_API_KEY;

  if (!serviceKey || !anthropicKey) {
    return new Response(
      JSON.stringify({
        error: 'Translation service not configured. Admin must set SUPABASE_SERVICE_KEY and ANTHROPIC_API_KEY in CF Pages env vars.',
      }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }

  let body: { id?: string };
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON body' }), { status: 400 });
  }

  const id = body?.id;
  if (!id) {
    return new Response(JSON.stringify({ error: 'Missing id' }), { status: 400 });
  }

  const supa = createClient(SUPABASE_URL, serviceKey, { auth: { persistSession: false } });

  // Fetch the record
  const { data: rec, error: fetchErr } = await supa
    .from('archive_results')
    .select('id, title, author, date_text, source, full_text, metadata')
    .eq('id', id)
    .maybeSingle();

  if (fetchErr || !rec) {
    return new Response(JSON.stringify({ error: 'Record not found' }), { status: 404 });
  }

  const md = (rec.metadata as any) ?? {};
  if (md.transcript_cg) {
    return new Response(
      JSON.stringify({ cached: true, transcript_cg: md.transcript_cg }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  }

  if (!rec.full_text) {
    return new Response(
      JSON.stringify({ error: 'No full_text available for this record. Translation requires source OCR text.' }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    );
  }

  // Cap input at 30KB to control cost (~$0.01 max per call with Haiku)
  const sourceText = rec.full_text.slice(0, 30_000);

  const prompt = `Ti si stručnjak za prevođenje istorijskih dokumenata na crnogorski jezik.

Tekst koji prevodiš je transkript istorijskog dokumenta o Ulcinju i okolini (može biti na latinskom, italijanskom, mletačkom, engleskom, francuskom, njemačkom, otomanskom turskom ili albanskom).

Tvoj zadatak:
1. **Prevedi tekst na crnogorski jezik** (latinica), zadržavajući istorijske termine, lična imena i nazive lokacija u izvornom obliku.
2. **Sačuvaj strukturu** (paragrafi, brojevi strana ako postoje).
3. **Označi sva pominjanja Ulcinja** (Olcinium, Dulcigno, Ulqin, Ülgün, Olgun) i okolnih lokacija (Bar, Antibarum, Skadar, Scodra, Svač, Bojana, Buna, Valdanos, Drivast, Lješ) **podebljanjem (markdown **bold**)** kao npr. **Olcinium**.
4. **Ako je tekst OCR sa greškama**, popravi očigledne tipfelere u prevodu (ali navedi u napomeni na kraju).
5. **Ako tekst nije relevantan za istraživanje Ulcinja** (npr. samo pomen u listi gradova bez konteksta), navedi to kratko na kraju.

Metapodaci dokumenta:
- Naslov: ${rec.title}
- Autor: ${rec.author || 'nepoznat'}
- Datum: ${rec.date_text || 'nepoznat'}
- Izvor: ${rec.source}

Tekst za prevod:
"""
${sourceText}
"""

Vrati samo prevedeni tekst (Markdown format). Ne dodaj uvod ili meta komentare osim eventualne kratke napomene na kraju.`;

  // Call Anthropic API
  const apiResp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': anthropicKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 8000,
      messages: [{ role: 'user', content: prompt }],
    }),
  });

  if (!apiResp.ok) {
    const errText = await apiResp.text();
    return new Response(
      JSON.stringify({ error: `Anthropic API ${apiResp.status}: ${errText.slice(0, 300)}` }),
      { status: 502, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const apiData = await apiResp.json();
  const transcript_cg = apiData?.content?.[0]?.text ?? '';

  if (!transcript_cg) {
    return new Response(JSON.stringify({ error: 'Empty translation response' }), { status: 502 });
  }

  // Cache to Supabase metadata
  const newMd = { ...md, transcript_cg, translated_at: new Date().toISOString() };
  await supa.from('archive_results').update({ metadata: newMd }).eq('id', id);

  return new Response(
    JSON.stringify({
      cached: false,
      transcript_cg,
      input_chars: sourceText.length,
      output_chars: transcript_cg.length,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } }
  );
};
