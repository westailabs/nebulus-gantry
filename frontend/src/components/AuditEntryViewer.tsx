import { useEffect, useState } from 'react';
import { chatApi } from '../services/api';
import type { Citation, MessageAuditEntry } from '../types/api';

interface AuditEntryViewerProps {
  messageId: number;
  /** Thread the answer belongs to; used only if no entry is stored for this exact answer. */
  conversationId?: number;
  /** Citations on the answer, used to show file names next to the logged doc ids. */
  sources?: Citation[];
  onClose: () => void;
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return 'unknown';
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function AuditRows({ entry, docName }: { entry: MessageAuditEntry; docName: (id: number) => string | undefined }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
      <dt className="text-gray-400">Entry</dt>
      <dd>#{entry.id}</dd>
      <dt className="text-gray-400">User</dt>
      <dd>{entry.user_email ?? 'unknown'}</dd>
      <dt className="text-gray-400">Time</dt>
      <dd>{formatTimestamp(entry.timestamp)}</dd>
      <dt className="text-gray-400">Action</dt>
      <dd className="font-mono text-xs leading-5">{entry.action}</dd>
      <dt className="text-gray-400">Documents</dt>
      <dd>
        {entry.doc_ids.length === 0 ? (
          'none'
        ) : (
          <ul>
            {entry.doc_ids.map((id) => (
              <li key={id}>
                #{id}
                {docName(id) ? ` · ${docName(id)}` : ''}
              </li>
            ))}
          </ul>
        )}
      </dd>
      {entry.detail.outcome && (
        <>
          <dt className="text-gray-400">Outcome</dt>
          <dd>{entry.detail.refused ? `${entry.detail.outcome} (refused)` : entry.detail.outcome}</dd>
        </>
      )}
      {entry.detail.correlation_id && (
        <>
          <dt className="text-gray-400">Correlation</dt>
          <dd className="font-mono text-xs leading-5">{entry.detail.correlation_id}</dd>
        </>
      )}
    </dl>
  );
}

/** Modal with the chat.query audit row behind one of the user's own answers (CPA demo mode). */
export function AuditEntryViewer({ messageId, conversationId, sources = [], onClose }: AuditEntryViewerProps) {
  const [entry, setEntry] = useState<MessageAuditEntry | null>(null);
  // Fallback: this thread's own entries, when none is keyed to this exact answer.
  const [threadEntries, setThreadEntries] = useState<MessageAuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    chatApi
      .getMessageAudit(messageId)
      .then((e) => {
        if (!cancelled) setEntry(e);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        if (conversationId == null) {
          setError(e.message || 'Could not load the audit entry');
          return;
        }
        chatApi
          .getConversationAudit(conversationId)
          .then((t) => {
            if (cancelled) return;
            if (t.entries.length > 0) setThreadEntries(t.entries);
            else setError(e.message || 'Could not load the audit entry');
          })
          .catch(() => {
            if (!cancelled) setError(e.message || 'Could not load the audit entry');
          });
      });
    return () => {
      cancelled = true;
    };
  }, [messageId, conversationId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const docName = (id: number) => sources.find((s) => s.document_id === id)?.filename;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Audit entry"
        className="w-full max-w-lg max-h-[80vh] overflow-hidden rounded-xl border border-gray-600 bg-gray-800 shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-700 px-4 py-3">
          <div className="text-sm font-semibold text-gray-100">Audit entry</div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-gray-100"
            aria-label="Close audit entry"
          >
            ✕
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-3 text-sm text-gray-200">
          {error && <p className="text-red-400">{error}</p>}
          {!error && !entry && !threadEntries && <p className="text-gray-400">Loading audit entry…</p>}
          {threadEntries && (
            <p className="mb-3 text-xs text-gray-400">
              No entry is stored for this exact answer, so this thread's logged entries are shown instead.
            </p>
          )}
          {entry && <AuditRows entry={entry} docName={docName} />}
          {threadEntries?.map((t) => (
            <div key={t.id} className="mb-3 border-t border-gray-700 pt-3 first:border-t-0 first:pt-0">
              <AuditRows entry={t} docName={docName} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
