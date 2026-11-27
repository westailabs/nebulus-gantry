import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../services/api', () => ({
  documentApi: { getChunk: vi.fn() },
  chatApi: { getMessageAudit: vi.fn() },
}));

import { chatApi, documentApi } from '../../services/api';
import { MessageBubble } from '../MessageBubble';
import { useConfigStore } from '../../stores/configStore';
import type { Message } from '../../types/api';

const answer: Message = {
  id: 42,
  conversation_id: 5,
  role: 'assistant',
  content: 'The 2025 AGI was $89,214 [1].',
  created_at: new Date().toISOString(),
  sources: [
    { n: 1, document_id: 7, filename: 'SAMPLE_whitfield_2025_form1040_summary.txt', chunk_index: 0, similarity: 0.45, snippet: 'AGI' },
  ],
};

const question: Message = { id: 41, conversation_id: 5, role: 'user', content: 'What AGI?', created_at: new Date().toISOString() };

describe('MessageBubble audit deep-link (CPA demo mode)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('demo mode: one click on the answer opens its chat.query audit row', async () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    vi.mocked(chatApi.getMessageAudit).mockResolvedValue({
      id: 9, timestamp: '2026-11-26T20:00:00+00:00', user_id: 2,
      user_email: 'sarah.chen@gantry-demo.example.com', action: 'chat.query', resource_type: 'conversation',
      resource_id: 5, doc_ids: [7], query_text: null,
      detail: { outcome: 'completed', refused: false, correlation_id: 'abc123def456', message_id: 42 },
    });
    render(<MessageBubble message={answer} />);
    fireEvent.click(screen.getByRole('button', { name: 'View audit entry' }));
    expect(chatApi.getMessageAudit).toHaveBeenCalledWith(42);
    const dialog = await screen.findByRole('dialog', { name: 'Audit entry' });
    await waitFor(() => expect(dialog).toHaveTextContent('sarah.chen@gantry-demo.example.com'));
    expect(dialog).toHaveTextContent('chat.query');
    expect(dialog).toHaveTextContent('#7 · SAMPLE_whitfield_2025_form1040_summary.txt');
    expect(dialog).toHaveTextContent('abc123def456');
  });

  it('demo mode: shows the API error instead of a fake entry', async () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    vi.mocked(chatApi.getMessageAudit).mockRejectedValue(new Error('No audit entry for this message'));
    render(<MessageBubble message={answer} />);
    fireEvent.click(screen.getByRole('button', { name: 'View audit entry' }));
    expect(await screen.findByText('No audit entry for this message')).toBeInTheDocument();
  });

  it('demo mode: citations still open the cited chunk', async () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    vi.mocked(documentApi.getChunk).mockResolvedValue({
      document_id: 7, filename: 'SAMPLE_whitfield_2025_form1040_summary.txt', chunk_index: 0, chunk_count: 1, text: 'AGI: $89,214',
    });
    render(<MessageBubble message={answer} />);
    fireEvent.click(screen.getByRole('button', { name: /\[1\] SAMPLE_whitfield_2025_form1040_summary\.txt/ }));
    expect(documentApi.getChunk).toHaveBeenCalledWith(7, 0);
    expect(await screen.findByText('AGI: $89,214')).toBeInTheDocument();
  });

  it('no audit link on user messages', () => {
    useConfigStore.setState({ demoMode: true, firmName: '', loaded: true });
    render(<MessageBubble message={question} />);
    expect(screen.queryByRole('button', { name: 'View audit entry' })).not.toBeInTheDocument();
  });

  it('flag off: no audit link', () => {
    useConfigStore.setState({ demoMode: false, firmName: '', loaded: true });
    render(<MessageBubble message={answer} />);
    expect(screen.queryByRole('button', { name: 'View audit entry' })).not.toBeInTheDocument();
  });
});
