import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { Sidebar } from '../Sidebar';
import { useUIStore, SIDEBAR_DEFAULT_WIDTH, SIDEBAR_MIN_WIDTH } from '../../stores/uiStore';

const longTitle = 'What is the capital of France and why does that matter for this client?';

vi.mock('../../stores/chatStore', () => ({
  useChatStore: () => ({
    conversations: [
      {
        id: 1,
        title: longTitle,
        pinned: false,
        persona_id: null,
        persona_name: null,
        document_scope: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
    currentConversationId: 1,
    isLoading: false,
    fetchConversations: vi.fn(),
    createConversation: vi.fn(),
    selectConversation: vi.fn(),
    deleteConversation: vi.fn(),
    pinConversation: vi.fn(),
    searchQuery: '',
    searchResults: [],
    isSearching: false,
    setSearchQuery: vi.fn(),
    performSearch: vi.fn(),
    clearSearch: vi.fn(),
  }),
}));

vi.mock('../KnowledgeVault', () => ({
  KnowledgeVault: () => <div data-testid="knowledge-vault" />,
}));

describe('Sidebar resize and titles', () => {
  beforeEach(() => {
    localStorage.clear();
    useUIStore.setState({ isSidebarOpen: true, sidebarWidth: SIDEBAR_DEFAULT_WIDTH });
  });

  it('exposes a keyboard-accessible resize handle and updates width on arrow keys', async () => {
    const user = userEvent.setup();
    render(<Sidebar />);
    const handle = screen.getByRole('separator', { name: 'Resize sidebar' });
    expect(handle).toHaveAttribute('aria-valuenow', String(SIDEBAR_DEFAULT_WIDTH));
    handle.focus();
    await user.keyboard('{ArrowRight}');
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH + 16);
    await user.keyboard('{ArrowLeft}');
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH);
    await user.keyboard('{Home}');
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_MIN_WIDTH);
    await user.keyboard('{Enter}');
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it('drags to a new width, clamps, and resets on double-click', () => {
    render(<Sidebar />);
    const handle = screen.getByRole('separator', { name: 'Resize sidebar' });
    fireEvent.pointerDown(handle, { button: 0, clientX: SIDEBAR_DEFAULT_WIDTH });
    fireEvent.pointerMove(handle, { clientX: SIDEBAR_DEFAULT_WIDTH + 80 });
    fireEvent.pointerUp(handle);
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH + 80);

    fireEvent.pointerDown(handle, { button: 0, clientX: 400 });
    fireEvent.pointerMove(handle, { clientX: 400 - 1000 });
    fireEvent.pointerUp(handle);
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_MIN_WIDTH);

    fireEvent.doubleClick(handle);
    expect(useUIStore.getState().sidebarWidth).toBe(SIDEBAR_DEFAULT_WIDTH);
  });

  it('shows the full title and a tooltip, and keeps action buttons out of the layout until hover', () => {
    render(<Sidebar />);
    const title = screen.getByText(longTitle);
    expect(title).toHaveAttribute('title', longTitle);
    expect(title.className).toMatch(/line-clamp-2/);
    const del = screen.getByRole('button', { name: 'Delete thread' });
    expect(del.parentElement?.className).toMatch(/hidden/);
    expect(del.parentElement?.className).toMatch(/group-hover:flex/);
  });
});
