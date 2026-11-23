import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.stubEnv('VITE_API_URL', '');

import { chatApi, documentApi, adminApi } from '../api';

function streamResponse(text: string) {
  const bytes = new TextEncoder().encode(text);
  let sent = false;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: () => {
          if (sent) return Promise.resolve({ done: true, value: undefined });
          sent = true;
          return Promise.resolve({ done: false, value: bytes });
        },
        releaseLock: () => {},
      }),
    },
  };
}

describe('citations API', () => {
  beforeEach(() => vi.clearAllMocks());

  it('yields a sources event before content', async () => {
    const src = [{ n: 1, document_id: 7, filename: 'a.txt', chunk_index: 0, similarity: 0.8, snippet: 'x' }];
    const sse =
      `event: sources\ndata: ${JSON.stringify(src)}\n\n` +
      `data: ${JSON.stringify({ content: 'AGI was $1 [1].' })}\n\n` +
      `event: done\ndata: ${JSON.stringify({ generation_time_ms: 5, sources: src })}\n\n`;
    global.fetch = vi.fn().mockResolvedValue(streamResponse(sse));
    const events = [];
    for await (const e of chatApi.sendMessage(1, 'q')) events.push(e);
    expect(events[0]).toEqual({ type: 'sources', sources: src });
    expect(events[1]).toEqual({ type: 'content', content: 'AGI was $1 [1].' });
    expect(events[2].type).toBe('done');
  });

  it('yields a replace event when the server cleans leaked reasoning', async () => {
    const sse =
      `data: ${JSON.stringify({ content: 'thinking... answer' })}\n\n` +
      `event: replace\ndata: ${JSON.stringify({ content: ' answer' })}\n\n` +
      `event: done\ndata: ${JSON.stringify({ generation_time_ms: 5 })}\n\n`;
    global.fetch = vi.fn().mockResolvedValue(streamResponse(sse));
    const events = [];
    for await (const e of chatApi.sendMessage(1, 'q')) events.push(e);
    expect(events[1]).toEqual({ type: 'replace', content: ' answer' });
    expect(events[2].type).toBe('done');
  });

  it('fetches a document chunk', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ text: 't' }) });
    await documentApi.getChunk(7, 2);
    expect(vi.mocked(global.fetch).mock.calls[0][0]).toBe('/api/documents/7/chunks/2');
  });

  it('lists audit events with filters', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ total: 0, events: [] }) });
    await adminApi.listAuditEvents({ action: 'chat.query', limit: 25 });
    expect(vi.mocked(global.fetch).mock.calls[0][0]).toBe('/api/admin/audit?action=chat.query&limit=25');
    expect(adminApi.auditCsvUrl({ action: 'auth.login' })).toBe('/api/admin/audit/export.csv?action=auth.login');
  });
});
