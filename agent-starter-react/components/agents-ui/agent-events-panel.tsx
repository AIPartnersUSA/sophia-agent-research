'use client';

import { useEffect, useMemo, useState } from 'react';
import { useTextStream } from '@livekit/components-react';

/**
 * LEVEL 2 + LEVEL 3 (per CHAT.md turn 30): live scrolling log of agent
 * events + per-stage latency metrics. Subscribes to the
 * `sophia.agent_events` text-stream topic published by sophia-agent's
 * worker (`_attach_event_publishers` in agent.py).
 *
 * Event kinds we render:
 *  - agent_state       (old -> new)
 *  - user_state        (old -> new)
 *  - user_transcript   (text, is_final, language)
 *  - speech_created
 *  - tools_executed
 *  - false_interruption
 *  - metrics           (stt_metrics | llm_metrics | tts_metrics | eou_metrics | vad_metrics)
 *  - error             (source class + message)
 *  - close
 *
 * Mounted as a fixed-position overlay on the bottom-left so it does not
 * collide with the RAG panel on the right or the chat-transcript in the
 * center.
 */

const EVENTS_TOPIC = 'sophia.agent_events';
const MAX_EVENTS = 50;

interface AgentEvent {
  ts: number;
  kind: string;
  id: string;
  [k: string]: unknown;
}

const KIND_STYLES: Record<string, { label: string; color: string }> = {
  agent_state: { label: 'AGENT', color: 'text-sky-300' },
  user_state: { label: 'USER ', color: 'text-emerald-300' },
  user_transcript: { label: 'TRANS', color: 'text-emerald-200' },
  speech_created: { label: 'SPEAK', color: 'text-sky-300' },
  tools_executed: { label: 'TOOLS', color: 'text-purple-300' },
  false_interruption: { label: 'FALSE', color: 'text-amber-300' },
  metrics: { label: 'METR ', color: 'text-zinc-300' },
  error: { label: 'ERROR', color: 'text-red-400' },
  close: { label: 'CLOSE', color: 'text-zinc-500' },
};

export function AgentEventsPanel() {
  const { textStreams } = useTextStream(EVENTS_TOPIC);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [showMetrics, setShowMetrics] = useState(true);

  useEffect(() => {
    if (!textStreams.length) return;
    const parsed: AgentEvent[] = [];
    for (const stream of textStreams) {
      try {
        const payload = JSON.parse(stream.text) as Record<string, unknown>;
        parsed.push({
          ts: typeof payload.ts === 'number' ? payload.ts : Date.now() / 1000,
          kind: typeof payload.kind === 'string' ? payload.kind : 'unknown',
          id: stream.streamInfo.id,
          ...payload,
        });
      } catch {
        // ignore malformed payloads
      }
    }
    parsed.sort((a, b) => a.ts - b.ts);
    setEvents(parsed.slice(-MAX_EVENTS));
  }, [textStreams]);

  const visibleEvents = useMemo(() => {
    if (showMetrics) return events;
    return events.filter((e) => e.kind !== 'metrics');
  }, [events, showMetrics]);

  return (
    <div className="pointer-events-none fixed bottom-4 left-4 z-40 flex w-[420px] max-w-[45vw] flex-col gap-2">
      <div className="pointer-events-auto flex items-center justify-between rounded-md bg-zinc-800/90 px-3 py-2 text-xs font-semibold text-zinc-100 shadow-md backdrop-blur-sm">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 hover:text-zinc-300"
        >
          <span>Agent events ({events.length})</span>
        </button>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-[10px] font-normal">
            <input
              type="checkbox"
              checked={showMetrics}
              onChange={(e) => setShowMetrics(e.target.checked)}
              className="h-3 w-3"
            />
            metrics
          </label>
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="hover:text-zinc-300"
            aria-expanded={!collapsed}
          >
            {collapsed ? '▴' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="pointer-events-auto flex max-h-[60vh] flex-col gap-1 overflow-y-auto rounded-md bg-zinc-900/90 p-2 shadow-lg backdrop-blur-sm">
          {visibleEvents.length === 0 && (
            <div className="px-1 py-2 text-xs text-zinc-500">
              Waiting for agent events. Start a call and speak to populate.
            </div>
          )}
          {visibleEvents.map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: AgentEvent }) {
  const style = KIND_STYLES[event.kind] ?? {
    label: event.kind.toUpperCase().slice(0, 5).padEnd(5),
    color: 'text-zinc-300',
  };
  const time = new Date(event.ts * 1000).toLocaleTimeString([], {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  return (
    <div className="grid grid-cols-[auto_auto_1fr] items-start gap-2 px-1 py-0.5 font-mono text-[11px] leading-tight">
      <span className="text-zinc-500">{time}</span>
      <span className={`font-semibold ${style.color}`}>{style.label}</span>
      <span className="text-zinc-200 break-words">
        {renderEventBody(event)}
      </span>
    </div>
  );
}

function renderEventBody(event: AgentEvent): string {
  switch (event.kind) {
    case 'agent_state':
    case 'user_state':
      return `${event.old} → ${event.new}`;
    case 'user_transcript': {
      const text = (event.text as string) ?? '';
      const isFinal = event.is_final;
      const tag = isFinal ? 'final' : 'partial';
      const lang = event.language ? ` [${event.language}]` : '';
      return `${tag}${lang}: "${text}"`;
    }
    case 'metrics': {
      const t = (event.metric_type as string) ?? 'unknown';
      const label = event.label ? ` (${event.label})` : '';
      const parts: string[] = [`${t}${label}`];
      // Pull the most informative timing fields per metric type.
      const candidates: [string, string][] = [
        ['ttft', 'ttft'],
        ['ttfb', 'ttfb'],
        ['duration', 'dur'],
        ['audio_duration', 'audio'],
        ['end_of_utterance_delay', 'eou'],
        ['transcription_delay', 'trans'],
        ['on_user_turn_completed_delay', 'on_turn'],
        ['completion_tokens', 'tokens_out'],
        ['prompt_tokens', 'tokens_in'],
      ];
      for (const [field, short] of candidates) {
        const v = event[field];
        if (typeof v === 'number') {
          parts.push(`${short}=${v.toFixed(field.endsWith('tokens') ? 0 : 2)}`);
        }
      }
      if (event.cancelled === true) parts.push('cancelled');
      return parts.join(' ');
    }
    case 'error':
      return `${event.source ?? '?'}: ${event.error ?? '(no detail)'}`;
    case 'false_interruption':
      return event.resumed ? 'resumed automatically' : 'NOT resumed';
    case 'speech_created':
    case 'tools_executed':
    case 'close':
      return '';
    default:
      // Show raw fields for unknown kinds
      return JSON.stringify(
        Object.fromEntries(
          Object.entries(event).filter(
            ([k]) => k !== 'ts' && k !== 'kind' && k !== 'id'
          )
        )
      );
  }
}
