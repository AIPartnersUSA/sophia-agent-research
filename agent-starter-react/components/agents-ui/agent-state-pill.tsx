'use client';

import { useAgent } from '@livekit/components-react';

/**
 * LEVEL 1 (per CHAT.md turn 30): a small pill that shows the agent's current
 * lifecycle state (initializing / idle / listening / thinking / speaking /
 * interrupted). LiveKit's framework already emits `agent_state_changed`
 * events into the room; the `useAgent` hook surfaces the current state.
 *
 * Mounted as a fixed-position overlay so it stays visible regardless of the
 * underlying layout.
 */

const STATE_STYLES: Record<string, { label: string; bg: string }> = {
  initializing: { label: 'initializing', bg: 'bg-zinc-700' },
  idle: { label: 'idle', bg: 'bg-zinc-600' },
  listening: { label: 'listening', bg: 'bg-emerald-700' },
  thinking: { label: 'thinking', bg: 'bg-amber-700' },
  speaking: { label: 'speaking', bg: 'bg-sky-700' },
};

export function AgentStatePill() {
  const { state } = useAgent();
  const style = STATE_STYLES[state ?? 'idle'] ?? STATE_STYLES.idle;

  return (
    <div className="pointer-events-none fixed top-4 left-4 z-40">
      <div
        className={`pointer-events-auto flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold text-zinc-100 shadow-md backdrop-blur-sm ${style.bg}`}
      >
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            state === 'speaking' || state === 'thinking'
              ? 'animate-pulse bg-zinc-100'
              : 'bg-zinc-300'
          }`}
        />
        <span>agent: {style.label}</span>
      </div>
    </div>
  );
}
