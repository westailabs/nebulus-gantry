import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../services/api', () => ({
  documentApi: { getChunk: vi.fn() },
}));

import { documentApi } from '../../services/api';
import { MessageBubble } from '../MessageBubble';
import type { Message } from '../../types/api';

const msg: Message = {
  id: 1,
  conversation_id: 1,
  role: 'assistant',
  content: 'AGI was $84,210 [1]. Engagement signed [2].',
  created_at: new Date().toISOString(),
  sources: [
    { n: 1, document_id: 7, filename: 'whitfield_2025_1040.txt', chunk_index: 0, similarity: 0.8, snippet: 'AGI' },
    { n: 2, document_id: 9, filename: 'whitfield_engagement.txt', chunk_index: 3, similarity: 0.5, snippet: 'EL' },
  ],
};

describe('MessageBubble citations', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders a source chip per citation', () => {
    render(<MessageBubble message={msg} />);
    expect(screen.getByRole('button', { name: /\[1\] whitfield_2025_1040\.txt/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[2\] whitfield_engagement\.txt/ })).toBeInTheDocument();
  });

  it('opens the source viewer from a chip', async () => {
    vi.mocked(documentApi.getChunk).mockResolvedValue({
      document_id: 7, filename: 'whitfield_2025_1040.txt', chunk_index: 0, chunk_count: 2, text: 'Line 11 AGI $84,210',
    });
    render(<MessageBubble message={msg} />);
    fireEvent.click(screen.getByRole('button', { name: /\[1\] whitfield_2025_1040\.txt/ }));
    expect(documentApi.getChunk).toHaveBeenCalledWith(7, 0);
    await waitFor(() => expect(screen.getByText('Line 11 AGI $84,210')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('makes inline [n] markers clickable', async () => {
    vi.mocked(documentApi.getChunk).mockResolvedValue({
      document_id: 9, filename: 'whitfield_engagement.txt', chunk_index: 3, chunk_count: 4, text: 'Signed 2026-01-10',
    });
    render(<MessageBubble message={msg} />);
    fireEvent.click(screen.getByRole('link', { name: '[2]' }));
    expect(documentApi.getChunk).toHaveBeenCalledWith(9, 3);
    await waitFor(() => expect(screen.getByText('Signed 2026-01-10')).toBeInTheDocument());
  });

  it('leaves messages without sources unchanged', () => {
    render(<MessageBubble message={{ ...msg, sources: undefined, content: 'plain [1]' }} />);
    expect(screen.queryByRole('link', { name: '[1]' })).toBeNull();
    expect(screen.queryByRole('button', { name: /\[1\]/ })).toBeNull();
  });
});
