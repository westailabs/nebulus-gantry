import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../services/api', () => ({
  documentApi: { getChunk: vi.fn() },
  chatApi: { getMessageAudit: vi.fn(), getConversationAudit: vi.fn() },
}));

import { MessageList } from '../MessageList';
import { useConfigStore } from '../../stores/configStore';
import type { Message } from '../../types/api';

const now = new Date().toISOString();
const saved: Message = { id: 10, conversation_id: 1, role: 'assistant', content: 'Saved answer', created_at: now };
const streaming: Message = { id: 1764200000001, conversation_id: 1, role: 'assistant', content: '', created_at: now };

// jsdom has no scrollIntoView; MessageList auto-scrolls on new messages.
Element.prototype.scrollIntoView = vi.fn();

describe('MessageList audit links (CPA demo mode)', () => {
  it('hides the link only on the unsaved streaming placeholder', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    render(<MessageList messages={[saved, streaming]} unsavedMessageId={streaming.id} />);
    expect(screen.getAllByRole('button', { name: 'View audit entry' })).toHaveLength(1);
  });

  it('shows a link on every saved answer once nothing is unsaved', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    render(<MessageList messages={[saved, { ...saved, id: 11 }]} unsavedMessageId={null} />);
    expect(screen.getAllByRole('button', { name: 'View audit entry' })).toHaveLength(2);
  });
});
