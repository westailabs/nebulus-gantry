import cpaStarterCards from './cpaStarterCards.json';

export interface QuickPrompt {
  label: string;
  prompt: string;
}

/** Default Gantry home-screen cards (flag off). */
export const DEFAULT_QUICK_PROMPTS: QuickPrompt[] = [
  { label: 'Explain some code', prompt: 'Help me understand this code and suggest improvements for readability and performance.' },
  { label: 'Brainstorm ideas', prompt: 'Help me brainstorm creative solutions for a technical challenge I\'m working on.' },
  { label: 'Write documentation', prompt: 'Help me write clear, concise documentation for my project.' },
  { label: 'Debug an issue', prompt: 'I\'m running into a bug. Help me trace the issue and find the root cause.' },
];

/**
 * CPA demo cards (GANTRY_DEMO_MODE). Questions over Client Files only. Shared with the
 * rehearsal script through cpaStarterCards.json so the two lists cannot drift.
 */
export const CPA_QUICK_PROMPTS: QuickPrompt[] = cpaStarterCards.cards.map(({ label, prompt }) => ({ label, prompt }));

export function quickPromptsFor(demoMode: boolean): QuickPrompt[] {
  return demoMode ? CPA_QUICK_PROMPTS : DEFAULT_QUICK_PROMPTS;
}
