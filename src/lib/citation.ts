import type { ArchiveResult } from './supabase';

function clean(s: string | null | undefined): string {
  return (s ?? '').replace(/[{}\\]/g, '').replace(/"/g, "'").trim();
}

function bibtexKey(rec: ArchiveResult): string {
  const author = rec.author?.split(/[\s,]+/)[0] ?? 'Anon';
  const year = rec.date_year_min ?? 0;
  const word = rec.title.replace(/[^a-zA-Z]/g, '').slice(0, 8);
  return `${author}${year}${word}`.replace(/[^a-zA-Z0-9]/g, '').slice(0, 30) || 'cite';
}

export function toBibtex(rec: ArchiveResult): string {
  const key = bibtexKey(rec);
  const year = rec.date_year_min?.toString() ?? '';
  const lines = [
    `@misc{${key},`,
    `  title  = {${clean(rec.title)}},`,
    rec.author ? `  author = {${clean(rec.author)}},` : null,
    year ? `  year   = {${year}},` : null,
    `  url    = {${rec.url_original}},`,
    `  note   = {Source: ${rec.source}}`,
    `}`,
  ].filter(Boolean);
  return lines.join('\n');
}

export function toApa(rec: ArchiveResult): string {
  const author = rec.author ?? 'Unknown Author';
  const year = rec.date_year_min?.toString() ?? 'n.d.';
  const title = rec.title;
  const source = rec.source;
  const url = rec.url_original;
  return `${author}. (${year}). ${title}. ${source}. ${url}`;
}

export function toChicago(rec: ArchiveResult): string {
  const author = rec.author ?? 'Unknown Author';
  const year = rec.date_year_min?.toString() ?? 'n.d.';
  const title = rec.title;
  const source = rec.source;
  const url = rec.url_original;
  return `${author}. "${title}." ${source}. ${year}. ${url}.`;
}
