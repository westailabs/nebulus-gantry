import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MessageInput } from '../MessageInput';
import { useAuthStore } from '../../stores/authStore';
import { useConfigStore } from '../../stores/configStore';

vi.mock('../../services/api', () => ({
  modelsApi: {
    list: vi.fn().mockResolvedValue({
      models: [
        { id: 'other-model', name: 'other-model', active: false },
        { id: 'bolt', name: 'bolt', active: true },
      ],
    }),
  },
}));

const admin = { id: 1, email: 'a@example.com', display_name: 'Setup Admin', role: 'admin' as const };
const member = { id: 2, email: 'u@example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

function setup(demoMode: boolean, user: typeof admin | typeof member) {
  useConfigStore.setState({ demoMode, firmName: '', loaded: true });
  useAuthStore.setState({ user, isLoading: false, error: null });
}

describe('MessageInput model picker vs CPA demo mode', () => {
  beforeEach(() => {
    setup(false, member);
  });

  it('flag off: non-admin still sees the model picker', async () => {
    setup(false, member);
    render(<MessageInput onSend={vi.fn()} />);
    expect(screen.getByTitle('Select model')).toBeInTheDocument();
  });

  it('demo mode + admin: model picker still available', () => {
    setup(true, admin);
    render(<MessageInput onSend={vi.fn()} />);
    expect(screen.getByTitle('Select model')).toBeInTheDocument();
  });

  it('demo mode + non-admin: no "Select model" control, and sending still works with no model override', async () => {
    setup(true, member);
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<MessageInput onSend={onSend} />);
    expect(screen.queryByTitle('Select model')).not.toBeInTheDocument();
    // let the model list load, so a selected model would exist if we used one
    await waitFor(() => expect(screen.getByRole('textbox')).toBeEnabled());
    await user.type(screen.getByRole('textbox'), 'Which clients are missing documents?{Enter}');
    expect(onSend).toHaveBeenCalledWith('Which clients are missing documents?', undefined);
  });
});
