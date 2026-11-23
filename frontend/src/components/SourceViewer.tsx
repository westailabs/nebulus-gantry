import { useEffect, useState } from 'react';
import { documentApi } from '../services/api';
import type { Citation, DocumentChunk } from '../types/api';

interface SourceViewerProps {
  citation: Citation;
  onClose: () => void;
}

/** Modal that shows the exact document chunk behind a citation. */
export function SourceViewer({ citation, onClose }: SourceViewerProps) {
  const [chunk, setChunk] = useState<DocumentChunk | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    documentApi
      .getChunk(citation.document_id, citation.chunk_index)
      .then((c) => {
        if (!cancelled) setChunk(c);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message || 'Could not load source');
      });
    return () => {
      cancelled = true;
    };
  }, [citation.document_id, citation.chunk_index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Source ${citation.n}: ${citation.filename}`}
        className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-xl border border-gray-600 bg-gray-800 shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-700 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-gray-100">
              [{citation.n}] {citation.filename}
            </div>
            <div className="text-xs text-gray-400">
              Chunk {citation.chunk_index + 1}
              {chunk ? ` of ${chunk.chunk_count}` : ''}
              {citation.similarity != null ? ` · match ${(citation.similarity * 100).toFixed(0)}%` : ''}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-gray-100"
            aria-label="Close source"
          >
            ✕
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-3">
          {error && <p className="text-sm text-red-400">{error}</p>}
          {!error && !chunk && <p className="text-sm text-gray-400">Loading source…</p>}
          {chunk && (
            <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-gray-200">
              {chunk.text}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
