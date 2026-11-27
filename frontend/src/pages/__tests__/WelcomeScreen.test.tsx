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
