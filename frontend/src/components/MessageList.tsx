import { useQueries } from "@tanstack/react-query";
import { useEffect } from "react";
import { Api } from "../api/client";
import type { Participant, RunDetail, RunEvent } from "../api/types";
import type { ThreadState } from "../lib/threadState";
import { parseTs } from "../lib/time";
import Avatar from "./Avatar";
import InterruptCard from "./InterruptCard";
import RunCard from "./RunCard";

const ACTIVE = ["queued", "running", "waiting_human"];

export default function MessageList({ state, participants, onRunLoaded }: { state: ThreadState; participants: Participant[]; onRunLoaded: (run: RunDetail) => void }) {
  const byActor = new Map(participants.map((p) => [p.actor_id, p]));
  // Runs referenced by a message whose events we do not have yet: fetch them lazily.
  // `onRunLoaded` folds the result into thread state, which drops the id from `missing`
  // and ends the fetch — the run itself must land in `state.runs`, because a completed
  // run is not in the thread payload and would otherwise disappear with the query.
  const missing = [...new Set(state.messages.map((m) => m.run_id).filter((r): r is string => !!r && !state.runEvents[r]))];
  const loaded = useQueries({ queries: missing.map((id) => ({ queryKey: ["run", id], queryFn: () => Api.getRun(id), staleTime: Infinity })) });
  useEffect(() => {
    loaded.forEach((q) => { const d = q.data as RunDetail | undefined; if (d) onRunLoaded(d); });
  });


  const eventsFor = (id: string): RunEvent[] => state.runEvents[id] ?? [];
  // A run whose reply message already exists is rendered under that message; keep it out
  // of the active strip so it is not shown twice while it finishes.
  const shown = new Set(state.messages.map((m) => m.run_id).filter((r): r is string => !!r));
  const active = Object.values(state.runs).filter((r) => ACTIVE.includes(r.status) && !shown.has(r.id));
  return (
    <div className="space-y-4">
      {state.messages.map((m) => {
        const run = m.run_id ? state.runs[m.run_id] : undefined;
        return (
          <div key={m.id} className={`flex gap-3 ${m.sender_kind === "system" ? "opacity-70" : ""}`}>
            <Avatar name={m.sender_name} kind={m.sender_kind} />
            <div className="min-w-0 flex-1">
              <div className="text-xs text-zinc-500">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">{m.sender_name}</span> · {parseTs(m.created_at).toLocaleTimeString()}{m.hop > 0 && ` · hop ${m.hop}`}
              </div>
              <div className="whitespace-pre-wrap text-sm">{m.content}</div>
              {run && <RunCard run={run} events={eventsFor(run.id)} streaming={state.streaming[run.id]} />}
              {run?.status === "waiting_human" && <InterruptCard run={run} botName={byActor.get(run.actor_id)?.name} />}
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
      {state.messages.length === 0 && active.length === 0 && <p className="text-sm text-zinc-500">No messages yet. Say hello; unmentioned messages go to the thread default bot.</p>}
    </div>
  );
}
