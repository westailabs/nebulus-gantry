import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../services/api';
import type { AuditEvent } from '../../types/api';

const ACTIONS = [
  '',
  'auth.login',
  'auth.login_failed',
  'auth.logout',
  'chat.query',
  'document.upload',
  'document.upload_failed',
  'document.view_source',
  'document.delete',
  'conversation.export',
  'conversation.bulk_export',
  'audit.export',
];

const PAGE = 100;

function formatTime(ts: string | null) {
  if (!ts) return '';
  // Stored as UTC; show in the viewer's local time zone.
  const d = new Date(ts.endsWith('Z') || ts.includes('+') ? ts : `${ts}Z`);
  return d.toLocaleString();
}

export function AuditTab() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [action, setAction] = useState('');
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminApi.listAuditEvents({ action: action || undefined, limit: PAGE, offset });
      setEvents(res.events);
      setTotal(res.total);
    } catch (e) {
      setError((e as Error).message || 'Failed to load audit log');
    } finally {
      setLoading(false);
    }
  }, [action, offset]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-n-text">Audit log</h2>
          <p className="text-sm text-n-muted">
            Who signed in, uploaded, asked, viewed sources, and exported — newest first. {total} events.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="text-xs text-n-muted">
            Action
            <select
              aria-label="Action"
              value={action}
              onChange={(e) => {
                setOffset(0);
                setAction(e.target.value);
              }}
              className="ml-2 rounded-md border border-n-border bg-n-bg px-2 py-1 text-sm text-n-text"
            >
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a || 'All actions'}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={load}
            className="rounded-md border border-n-border px-3 py-1 text-sm text-n-text hover:bg-n-hover"
          >
            Refresh
          </button>
          <a
            href={adminApi.auditCsvUrl({ action: action || undefined })}
            className="rounded-md bg-n-accent px-3 py-1 text-sm font-medium text-white hover:opacity-90"
          >
            Export CSV
          </a>
        </div>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="overflow-x-auto rounded-lg border border-n-border">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-n-panel text-xs uppercase text-n-muted">
            <tr>
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">User</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Resource</th>
              <th className="px-3 py-2">Docs</th>
              <th className="px-3 py-2">Query</th>
              <th className="px-3 py-2">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-n-border">
            {events.map((e) => (
              <tr key={e.id} className="align-top text-n-text">
                <td className="whitespace-nowrap px-3 py-2 text-n-muted">{formatTime(e.timestamp)}</td>
                <td className="px-3 py-2">{e.user_email ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-xs">{e.action}</td>
                <td className="px-3 py-2 text-n-muted">
                  {e.resource_type ? `${e.resource_type} ${e.resource_id ?? ''}` : ''}
                </td>
                <td className="px-3 py-2">{e.doc_ids.length ? e.doc_ids.join(', ') : ''}</td>
                <td className="max-w-xs px-3 py-2 break-words">{e.query_text ?? ''}</td>
                <td className="max-w-xs px-3 py-2 font-mono text-xs text-n-muted break-words">
                  {Object.keys(e.detail).length ? JSON.stringify(e.detail) : ''}
                </td>
              </tr>
            ))}
            {!loading && events.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-n-muted">
                  No audit events.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
            className="rounded border border-n-border px-2 py-1 disabled:opacity-40"
          >
            Newer
          </button>
          <span className="text-n-muted">
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <button
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
            className="rounded border border-n-border px-2 py-1 disabled:opacity-40"
          >
            Older
          </button>
        </div>
      )}
    </div>
  );
}
