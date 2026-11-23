import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../../../services/api', () => ({
  adminApi: {
    listAuditEvents: vi.fn(),
    auditCsvUrl: vi.fn(() => '/api/admin/audit/export.csv'),
  },
}));

import { adminApi } from '../../../services/api';
import { AuditTab } from '../AuditTab';

describe('AuditTab', () => {
  it('lists events and offers CSV export', async () => {
    vi.mocked(adminApi.listAuditEvents).mockResolvedValue({
      total: 1,
      events: [{
        id: 1, timestamp: '2026-11-22T23:00:00', user_id: 1, user_email: 'admin@x.com', action: 'chat.query',
        resource_type: 'conversation', resource_id: 3, doc_ids: [7, 9], query_text: 'what did we file',
        detail: { refused: false }, ip_address: '127.0.0.1',
      }],
    });
    render(<AuditTab />);
    await waitFor(() => expect(screen.getByText('chat.query')).toBeInTheDocument());
    expect(screen.getByText('admin@x.com')).toBeInTheDocument();
    expect(screen.getByText('7, 9')).toBeInTheDocument();
    expect(screen.getByText('what did we file')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /export csv/i })).toHaveAttribute('href', '/api/admin/audit/export.csv');
  });

  it('filters by action', async () => {
    vi.mocked(adminApi.listAuditEvents).mockResolvedValue({ total: 0, events: [] });
    render(<AuditTab />);
    fireEvent.change(screen.getByLabelText(/action/i), { target: { value: 'auth.login' } });
    await waitFor(() =>
      expect(adminApi.listAuditEvents).toHaveBeenLastCalledWith(expect.objectContaining({ action: 'auth.login' })),
    );
  });
});
