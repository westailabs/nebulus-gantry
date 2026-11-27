import { describe, it, expect } from 'vitest';
import { CPA_QUICK_PROMPTS, DEFAULT_QUICK_PROMPTS, quickPromptsFor } from '../quickPrompts';

const CPA_LABELS = [
  'Which clients are still missing documents?',
  'Ask about a client email or IRS notice',
  "Summarize a client's 1099s",
  'Year-over-year return changes',
];
const CODE_LABELS = ['Explain some code', 'Brainstorm ideas', 'Write documentation', 'Debug an issue'];

describe('starter card lists', () => {
  it('flag off keeps the four code-oriented cards', () => {
    expect(quickPromptsFor(false).map((p) => p.label)).toEqual(CODE_LABELS);
    expect(DEFAULT_QUICK_PROMPTS).toHaveLength(4);
  });

  it('flag on uses exactly the four CPA Client Files cards', () => {
    expect(quickPromptsFor(true).map((p) => p.label)).toEqual(CPA_LABELS);
  });

  it('no engagement-letter or tax-law research card in either mode', () => {
    for (const p of [...CPA_QUICK_PROMPTS, ...DEFAULT_QUICK_PROMPTS]) {
      const text = `${p.label} ${p.prompt}`.toLowerCase();
      expect(text).not.toMatch(/engagement letter/);
      expect(text).not.toMatch(/tax[- ]law|research|irc §|internal revenue code/);
    }
  });

  it('every CPA prompt is a question over Client Files, not a generation task', () => {
    for (const p of CPA_QUICK_PROMPTS) {
      expect(p.prompt.trim().endsWith('?') || /^summarize\b/i.test(p.prompt)).toBe(true);
      expect(p.prompt.toLowerCase()).not.toMatch(/\b(draft|write|compose|generate|prepare a letter)\b/);
    }
  });

  it('the IRS-notice card points at the synthetic Whitfield CP2000', () => {
    const notice = CPA_QUICK_PROMPTS.find((p) => p.label.includes('IRS notice'));
    expect(notice?.prompt).toMatch(/CP2000/);
    expect(notice?.prompt).toMatch(/Whitfield/);
  });
});

describe('demo-mode copy guard', () => {
  it('starter-card copy makes no offline, SOC 2, Safeguards, HIPAA or IRS-compliance claim', () => {
    const forbidden = [/network not required/i, /\boffline\b/i, /on-premises/i, /\bSOC\s?2\b/i, /safeguards/i,
      /\bHIPAA\b/i, /IRS[- ](compliant|compliance|approved|certified)/i];
    const text = CPA_QUICK_PROMPTS.map((p) => `${p.label} ${p.prompt}`).join(' ');
    for (const pattern of forbidden) expect(text).not.toMatch(pattern);
  });
});
