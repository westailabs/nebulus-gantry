import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { WelcomeScreen } from '../Chat';
import { useAuthStore } from '../../stores/authStore';
import { useConfigStore } from '../../stores/configStore';

vi.mock('../../components/MessageInput', () => ({ MessageInput: () => <div data-testid="message-input" /> }));
vi.mock('../../services/api', () => ({ chatApi: {}, dispatchApi: {} }));

const member = { id: 2, email: 'sarah.chen@gantry-demo.example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

function renderWelcome(demoMode: boolean, firmName = '') {
  useConfigStore.setState({ demoMode, firmName, loaded: true });
  useAuthStore.setState({ user: member, isLoading: false, error: null });
  return render(<WelcomeScreen onSend={vi.fn()} isSending={false} />);
}

describe('WelcomeScreen starter cards (issue 2)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('flag on: the four CPA cards render and the code cards do not', () => {
    renderWelcome(true);
    for (const label of [
      'Which clients are still missing documents?',
      'Ask about a client email or IRS notice',
      "Summarize a client's 1099s",
      'Year-over-year return changes',
    ]) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: 'Explain some code' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Debug an issue' })).not.toBeInTheDocument();
  });

  it('flag off: the code-oriented four still render', () => {
    renderWelcome(false);
    for (const label of ['Explain some code', 'Brainstorm ideas', 'Write documentation', 'Debug an issue']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: 'Year-over-year return changes' })).not.toBeInTheDocument();
  });
});

// Copy that must never appear in the demo-mode UI until it has been proven live.
const FORBIDDEN_DEMO_COPY = [
  /network not required/i,
  /\boffline\b/i,
  /on-premises/i,
  /\bSOC\s?2\b/i,
  /safeguards/i,
  /\bHIPAA\b/i,
  /IRS[- ](compliant|compliance|approved|certified)/i,
  /compliant with (the )?IRS/i,
];

describe('WelcomeScreen subtitle and mark (issue 4)', () => {
  it('flag on: subtitle is exactly "Your data stays on your own hardware", no motorcycle emoji', () => {
    renderWelcome(true);
    const subtitle = screen.getByText('Your data stays on your own hardware');
    expect(subtitle.textContent).toBe('Your data stays on your own hardware');
    expect(document.body.textContent).not.toContain('Ask me anything');
    expect(document.body.textContent).not.toContain('🏍');
    expect(screen.getByTestId('welcome-mark')).toBeInTheDocument();
  });

  it('flag off: subtitle and emoji unchanged', () => {
    renderWelcome(false);
    expect(screen.getByText('Your data stays on this device. Ask me anything.')).toBeInTheDocument();
    expect(document.body.textContent).toContain('🏍️');
  });

  it('keeps the time-of-day greeting with the first name', () => {
    renderWelcome(true);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/^Good (morning|afternoon|evening), Sarah\.$/);
  });

  it('flag on: no network/offline/on-premises badge and no SOC 2, Safeguards, HIPAA or IRS-compliance claim', () => {
    renderWelcome(true, 'Sample & Co. CPAs');
    const text = document.body.textContent ?? '';
    for (const pattern of FORBIDDEN_DEMO_COPY) {
      expect(text).not.toMatch(pattern);
    }
  });
});

describe('WelcomeScreen light white-label (issue 5)', () => {
  it('flag on: shows the configured firm name and "Powered by West AI Labs"', () => {
    renderWelcome(true, 'Sample & Co. CPAs');
    expect(screen.getByTestId('demo-firm-name')).toHaveTextContent('Sample & Co. CPAs');
    expect(screen.getByText('Powered by West AI Labs')).toBeInTheDocument();
  });

  it('flag on without a firm name: no empty firm line, still "Powered by"', () => {
    renderWelcome(true, '');
    expect(screen.queryByTestId('demo-firm-name')).not.toBeInTheDocument();
    expect(screen.getByText('Powered by West AI Labs')).toBeInTheDocument();
  });

  it('flag off: no firm name and no "Powered by" even if a firm name is configured', () => {
    renderWelcome(false, 'Sample & Co. CPAs');
    expect(screen.queryByTestId('demo-firm-name')).not.toBeInTheDocument();
    expect(screen.queryByText('Powered by West AI Labs')).not.toBeInTheDocument();
  });

  it('greets the walkthrough user by first name, never "Demo"', () => {
    renderWelcome(true, 'Sample & Co. CPAs');
    const greeting = screen.getByRole('heading', { level: 2 }).textContent ?? '';
    expect(greeting).toContain('Sarah');
    expect(document.body.textContent).not.toMatch(/Demo Admin|Moto test/);
  });
});
