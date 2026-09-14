import { useQueries } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Api } from "../api/client";
import type { Participant, Run, RunDetail, RunEvent } from "../api/types";
import type { ThreadState } from "../lib/threadState";
import Avatar from "./Avatar";
import InterruptCard from "./InterruptCard";
import RunCard from "./RunCard";

const ACTIVE = ["queued", "running", "waiting_human"];

export default function MessageList({ state, participants, onRunLoaded }: { state: ThreadState; participants: Participant[]; onRunLoaded: (runId: string, events: RunEvent[]) => void }) {
  const byActor = new Map(participants.map((p) => [p.actor_id, p]));
  const bottom = useRef<HTMLDivElement>(null);
  // Runs referenced by a message whose events we do not have yet: fetch them lazily.
  const missing = [...new Set(state.messages.map((m) => m.run_id).filter((r): r is string => !!r && !state.runEvents[r]))];
  const loaded = useQueries({ queries: missing.map((id) => ({ queryKey: ["run", id], queryFn: () => Api.getRun(id), staleTime: Infinity })) });

  // Hand each fetched run's events to the parent exactly once (a ref, not a dependency
  // list, guards against the re-render the parent's setState triggers).
  const reported = useRef(new Set<string>());
  useEffect(() => {
    loaded.forEach((q) => {
      const d = q.data as RunDetail | undefined;
      if (d && !reported.current.has(d.id)) {
        reported.current.add(d.id);
        onRunLoaded(d.id, d.events);
      }
    });
  });

  const fetched = new Map<string, RunDetail>();
  loaded.forEach((q) => { const d = q.data as RunDetail | undefined; if (d) fetched.set(d.id, d); });
  const runFor = (id: string): Run | undefined => state.runs[id] ?? fetched.get(id);
  const eventsFor = (id: string): RunEvent[] => state.runEvents[id] ?? fetched.get(id)?.events ?? [];

  const streamedChars = Object.values(state.streaming).reduce((a, s) => a + s.length, 0);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [state.messages.length, streamedChars]);

  const active = Object.values(state.runs).filter((r) => ACTIVE.includes(r.status));
  return (
    <div className="space-y-4">
      {state.messages.map((m) => {
        const run = m.run_id ? runFor(m.run_id) : undefined;
        return (
          <div key={m.id} className={`flex gap-3 ${m.sender_kind === "system" ? "opacity-70" : ""}`}>
            <Avatar name={m.sender_name} kind={m.sender_kind} />
            <div className="min-w-0 flex-1">
              <div className="text-xs text-zinc-500">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">{m.sender_name}</span> · {new Date(m.created_at).toLocaleTimeString()}{m.hop > 0 && ` · hop ${m.hop}`}
              </div>
              <div className="whitespace-pre-wrap text-sm">{m.content}</div>
              {run && <RunCard run={run} events={eventsFor(run.id)} />}
            </div>
          </div>
        );
      })}
      {active.map((r) => (
        <div key={r.id} className="flex gap-3">
          <Avatar name={byActor.get(r.actor_id)?.name ?? "bot"} kind="bot" />
          <div className="min-w-0 flex-1 space-y-1">
            <div className="text-xs text-zinc-500">{byActor.get(r.actor_id)?.name ?? "bot"} · {r.status.replace("_", " ")}</div>
            <RunCard run={r} events={eventsFor(r.id)} streaming={state.streaming[r.id]} />
            {r.status === "waiting_human" && <InterruptCard run={r} botName={byActor.get(r.actor_id)?.name} />}
          </div>
        </div>
      ))}
      {state.messages.length === 0 && active.length === 0 && <p className="text-sm text-zinc-500">No messages yet. Say hello and mention a bot with @handle.</p>}
      <div ref={bottom} />
    </div>
  );
}
