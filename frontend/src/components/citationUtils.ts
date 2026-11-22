import type { Citation } from '../types/api';

export const SOURCE_HREF = '#source-';

/** Turn inline [1] / [1, 2] markers that match known sources into source links. */
export function linkCitations(text: string, sources: Citation[] | null | undefined): string {
  if (!sources || sources.length === 0) return text;
  const known = new Set(sources.map((s) => s.n));
  return text.replace(/\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g, (match, nums: string) => {
    const ns = nums.split(',').map((x) => parseInt(x.trim(), 10));
    if (!ns.every((n) => known.has(n))) return match;
    return ns.map((n) => `[\\[${n}\\]](${SOURCE_HREF}${n})`).join(' ');
  });
}
