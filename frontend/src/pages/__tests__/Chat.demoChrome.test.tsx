import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { Chat } from '../Chat';
import { useAuthStore } from '../../stores/authStore';
import { useConfigStore } from '../../stores/configStore';
import { useChatStore } from '../../stores/chatStore';
import { useDispatchStore } from '../../stores/dispatchStore';

vi.mock('../../components/Sidebar', () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock('../../components/MessageList', () => ({ MessageList: () => <div data-testid="message-list" /> }));
vi.mock('../../components/MessageInput', () => ({ MessageInput: () => <div data-testid="message-input" /> }));
vi.mock('../../components/PersonaSelector', () => ({ PersonaSelector: () => null }));
vi.mock('../../components/DocumentScopeSelector', () => ({ DocumentScopeSelector: () => null }));
vi.mock('../../components/ExportActions', () => ({ ExportActions: () => null }));
vi.mock('../../components/SituationMap', () => ({ SituationMap: () => <div data-testid="situation-map" /> }));
vi.mock('../../services/api', () => ({
  chatApi: {
    getConversation: vi.fn().mockResolvedValue({
      conversation: { id: 7, title: 'Whitfield review', pinned: false, created_at: '', updated_at: '' },
      messages: [],
    }),
  },
  dispatchApi: { sendMessage: vi.fn() },
}));

const admin = { id: 1, email: 'a@example.com', display_name: 'Setup Admin', role: 'admin' as const };
const member = { id: 2, email: 'u@example.com', display_name: 'Sarah Chen, CPA', role: 'user' as const };

function setup(demoMode: boolean, user: typeof admin | typeof member, mapOpen: boolean) {
  useConfigStore.setState({ demoMode, firmName: '', loaded: true });
  useAuthStore.setState({ user, isLoading: false, error: null });
  useChatStore.setState({ currentConversationId: 7 });
  useDispatchStore.setState({ sidebarOpen: mapOpen, events: [] });
}

describe('Chat dev chrome vs CPA demo mode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('demo mode + non-admin: no Situation Map toggle and no SituationMap, even if it was left open', () => {
    setup(true, member, false);
    const { unmount } = render(<Chat />);
    expect(screen.queryByTitle('Situation Map')).not.toBeInTheDocument();
    unmount();
    setup(true, member, true);
    render(<Chat />);
    expect(screen.queryByTestId('situation-map')).not.toBeInTheDocument();
  });

  it('demo mode + admin: Situation Map toggle and panel still available', () => {
    setup(true, admin, false);
    const { unmount } = render(<Chat />);
    expect(screen.getByTitle('Situation Map')).toBeInTheDocument();
    unmount();
    setup(true, admin, true);
    render(<Chat />);
    expect(screen.getByTestId('situation-map')).toBeInTheDocument();
  });

  it('flag off: non-admin keeps today\'s Situation Map toggle and panel', () => {
    setup(false, member, false);
    const { unmount } = render(<Chat />);
    expect(screen.getByTitle('Situation Map')).toBeInTheDocument();
    unmount();
    setup(false, member, true);
    render(<Chat />);
    expect(screen.getByTestId('situation-map')).toBeInTheDocument();
  });
});
