'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTextStream } from '@livekit/components-react';

/**
 * Subscribes to the `sophia.rag_result` text-stream topic published by the
 * sophia-agent worker every time the `lookup_manual` function_tool is called.
 *
 * Each message is a JSON-encoded payload:
 *   {
 *     question: string,
 *     answer: string,
 *     hits: Array<{ source: string; page?: number; score?: number; ... }>,
 *     images: Array<{ source: string; page: number }>,
 *     mode: string,
 *     status?: "success" | "error",
 *     error?: string,
 *   }
 *
 * Renders the most recent N results as cards in a fixed right-side overlay.
 */

const RAG_RESULT_TOPIC = 'sophia.rag_result';
const MAX_RESULTS = 5;

interface RagHit {
  source?: string;
  page?: number;
  score?: number;
  // Chunk text from the retrieval. Field name varies by RAG backend;
  // try multiple fallbacks (text / snippet / content / page_content).
  text?: string;
  snippet?: string;
  content?: string;
  page_content?: string;
}

/** Extract the actual chunk text from a hit, trying common field names. */
function getHitText(h: RagHit): string {
  return (h.text ?? h.snippet ?? h.content ?? h.page_content ?? '').trim();
}

const SNIPPET_PREVIEW_CHARS = 180;

interface RagImage {
  source: string;
  page: number;
}

interface RagPayload {
  status?: string;
  question?: string;
  answer?: string;
  hits?: RagHit[];
  images?: RagImage[];
  mode?: string;
  error?: string;
}

interface ParsedResult extends RagPayload {
  receivedAt: number;
  id: string;
}

export function RagResultPanel() {
  const { textStreams } = useTextStream(RAG_RESULT_TOPIC);
  const [results, setResults] = useState<ParsedResult[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (!textStreams.length) return;
    const parsed: ParsedResult[] = [];
    for (const stream of textStreams) {
      try {
        const payload = JSON.parse(stream.text) as RagPayload;
        parsed.push({
          ...payload,
          receivedAt: stream.streamInfo.timestamp ?? Date.now(),
          id: stream.streamInfo.id,
        });
      } catch {
        // ignore malformed payloads (shouldn't happen, but guard anyway)
      }
    }
    parsed.sort((a, b) => b.receivedAt - a.receivedAt);
    setResults(parsed.slice(0, MAX_RESULTS));
  }, [textStreams]);

  const hasResults = results.length > 0;

  const headerLabel = useMemo(() => {
    if (!hasResults) return 'RAG results';
    return `RAG results (${results.length})`;
  }, [hasResults, results.length]);

  return (
    <div className="pointer-events-none fixed top-4 right-4 z-40 flex w-[360px] max-w-[40vw] flex-col gap-2">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="pointer-events-auto flex items-center justify-between rounded-md bg-zinc-800/90 px-3 py-2 text-xs font-semibold text-zinc-100 shadow-md backdrop-blur-sm hover:bg-zinc-700/90"
        aria-expanded={!collapsed}
      >
        <span>{headerLabel}</span>
        <span>{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="pointer-events-auto flex max-h-[80vh] flex-col gap-2 overflow-y-auto">
          {!hasResults && (
            <div className="rounded-md bg-zinc-900/80 px-3 py-2 text-xs text-zinc-400 backdrop-blur-sm">
              Ask Sophia about an industrial equipment manual and the
              retrieved sources, page references, and mode will appear here.
            </div>
          )}
          {results.map((r) => (
            <RagCard key={r.id} result={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function RagCard({ result }: { result: ParsedResult }) {
  const sources = useMemo(() => {
    if (!result.hits) return [];
    const unique = new Map<string, RagHit[]>();
    for (const h of result.hits) {
      if (!h.source) continue;
      const arr = unique.get(h.source) ?? [];
      arr.push(h);
      unique.set(h.source, arr);
    }
    return Array.from(unique.entries()); // [[source, hits[]], ...]
  }, [result.hits]);

  const isError = result.status === 'error';
  const time = new Date(result.receivedAt).toLocaleTimeString();

  return (
    <div className="rounded-md bg-zinc-900/90 p-3 text-xs text-zinc-100 shadow-lg backdrop-blur-sm">
      <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-wider text-zinc-400">
        <span>{result.mode ?? (isError ? 'error' : 'unknown')}</span>
        <span>{time}</span>
      </div>

      {result.question && (
        <div className="mb-2">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            Question
          </div>
          <div className="text-zinc-200">{result.question}</div>
        </div>
      )}

      {isError ? (
        <div className="rounded bg-red-900/40 px-2 py-1 text-red-200">
          {result.error ?? 'Unknown error'}
        </div>
      ) : (
        <>
          <div className="mb-2">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">
              Answer
            </div>
            <div className="whitespace-pre-wrap text-zinc-100">
              {result.answer || '(empty)'}
            </div>
          </div>

          {sources.length > 0 && (
            <div className="mb-2">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                Sources ({sources.length})
              </div>
              <ul className="mt-1 space-y-2">
                {sources.map(([source, hits]) => (
                  <li
                    key={source}
                    className="rounded bg-zinc-800/80 px-2 py-1"
                  >
                    <div className="truncate font-mono text-[11px] text-zinc-200">
                      {source}
                    </div>
                    <ul className="mt-1 space-y-1.5">
                      {hits.map((h, i) => (
                        <HitChunk key={`${source}-${i}`} hit={h} />
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.images && result.images.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                Reference pages ({result.images.length})
              </div>
              <ul className="mt-1 flex flex-wrap gap-1">
                {result.images.map((img, i) => (
                  <li
                    key={`${img.source}-${img.page}-${i}`}
                    className="rounded bg-zinc-800/80 px-2 py-1 font-mono text-[10px] text-zinc-300"
                    title={img.source}
                  >
                    {img.source.replace(/\.pdf$/i, '')} p.{img.page}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function HitChunk({ hit }: { hit: RagHit }) {
  const [expanded, setExpanded] = useState(false);
  const text = getHitText(hit);
  const tooLong = text.length > SNIPPET_PREVIEW_CHARS;
  const visible =
    !tooLong || expanded ? text : text.slice(0, SNIPPET_PREVIEW_CHARS) + '...';

  return (
    <li className="rounded bg-zinc-900/60 px-2 py-1">
      <div className="text-[10px] text-zinc-400">
        {hit.page !== undefined ? `p.${hit.page}` : '—'}
        {hit.score !== undefined && (
          <span className="ml-2">score {hit.score.toFixed(2)}</span>
        )}
      </div>
      {text ? (
        <>
          <div className="mt-0.5 whitespace-pre-wrap text-[11px] text-zinc-100">
            {visible || '(empty chunk text)'}
          </div>
          {tooLong && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-0.5 text-[10px] text-zinc-400 underline hover:text-zinc-200"
            >
              {expanded ? 'show less' : 'show more'}
            </button>
          )}
        </>
      ) : (
        <div className="mt-0.5 text-[10px] text-zinc-500 italic">
          (no chunk text in payload)
        </div>
      )}
    </li>
  );
}
