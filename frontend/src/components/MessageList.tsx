import { useQueries } from "@tanstack/react-query";
import { useEffect } from "react";
import { Api } from "../api/client";
import type { Message, MessageAttachment, Participant, RunDetail, RunEvent } from "../api/types";
import type { ThreadState } from "../lib/threadState";
import { parseTs } from "../lib/time";
import Avatar from "./Avatar";
import InterruptCard from "./InterruptCard";
import MarkdownContent from "./MarkdownContent";
import RunCard from "./RunCard";
import ThinkingPlaceholder from "./ThinkingPlaceholder";

const ACTIVE = ["queued", "running", "waiting_human"];
export default function MessageList({ state, participants, onRunLoaded, iconByActor, nameByActor }: { state: ThreadState; participants: Participant[]; onRunLoaded: (run: RunDetail) => void; iconByActor?: Record<string, string>; nameByActor?: Record<string, string> }) {
  const byActor = new Map(participants.map((p) => [p.actor_id, p]));
  const missing = [...new Set(state.messages.map((m) => m.run_id).filter((r): r is string => !!r && !state.runEvents[r]))];
  const loaded = useQueries({ queries: missing.map((id) => ({ queryKey: ["run", id], queryFn: () => Api.getRun(id), staleTime: Infinity })) });
  useEffect(() => { loaded.forEach((q) => { const d = q.data as RunDetail | undefined; if (d) onRunLoaded(d); }); });
  const eventsFor = (id: string): RunEvent[] => state.runEvents[id] ?? [];
  const messageImages = (m: Message): MessageAttachment[] => {
    const raw = m.metadata?.attachments;
    if (Array.isArray(raw) && raw.length > 0) return raw.filter((a): a is MessageAttachment => !!a && typeof a === "object" && typeof (a as MessageAttachment).url === "string");
    const legacy = m.metadata?.images;
    return Array.isArray(legacy) ? legacy.filter((u): u is string => typeof u === "string" && !!u).map((url) => ({ url })) : [];
  };
  const shown = new Set(state.messages.map((m) => m.run_id).filter((r): r is string => !!r));
  const active = Object.values(state.runs).filter((r) => ACTIVE.includes(r.status) && !shown.has(r.id));
  const botName = (actorId: string): string | undefined => byActor.get(actorId)?.name ?? nameByActor?.[actorId];
  return <div className="space-y-8">
    {state.messages.map((m) => {
      const run = m.run_id ? state.runs[m.run_id] : undefined;
      const kind = m.sender_kind;
      return <div key={m.id} className={`message-sheet flex gap-3 ${kind === "user" ? "message-user" : kind === "system" ? "message-system" : "message-assistant"}`}>
        <Avatar name={m.sender_name} kind={kind} icon={m.sender_actor_id ? iconByActor?.[m.sender_actor_id] : undefined} />
        <div className="min-w-0 flex-1"><div className="message-meta"><span className="font-medium text-[#20241f] dark:text-[#eef1eb]">{m.sender_name}</span> · {parseTs(m.created_at).toLocaleTimeString()}{m.hop > 0 && ` · hop ${m.hop}`}</div>
          <MarkdownContent content={m.content} />
          {messageImages(m).length > 0 && <div className="mt-2 flex flex-wrap gap-2">{messageImages(m).map((a, i) => <figure key={`${m.id}:${i}`} className="m-0"><img src={a.url} alt={`image attached to message by ${m.sender_name}`} className="max-h-40 rounded border border-[#d7dbd3] dark:border-[#3b413a]" />{a.name && <figcaption className="mt-0.5 max-h-40 truncate text-xs text-[#687067]">{a.name}</figcaption>}</figure>)}</div>}
          {run && <RunCard run={run} events={eventsFor(run.id)} streaming={state.streaming[run.id]} />}{run?.status === "waiting_human" && <InterruptCard run={run} botName={botName(run.actor_id)} />}
        </div></div>;
    })}
    {active.map((r) => {
      const events = eventsFor(r.id);
      const stream = state.streaming[r.id];
      const hasContent = events.length > 0 || !!stream;
      // Show the lightweight ThinkingPlaceholder when the run is still empty
      // (no tool calls, no streaming text yet). Once content arrives, the
      // full RunCard takes over so the user sees the work in progress.
      if (!hasContent && (r.status === "queued" || r.status === "running")) {
        return <ThinkingPlaceholder key={r.id} botName={botName(r.actor_id) ?? "bot"} icon={iconByActor?.[r.actor_id]} />;
      }
      return <div key={r.id} className="message-sheet message-assistant flex gap-3"><Avatar name={botName(r.actor_id) ?? "bot"} kind="bot" icon={iconByActor?.[r.actor_id]} /><div className="min-w-0 flex-1 space-y-1"><div className="message-meta">{botName(r.actor_id) ?? "bot"} · {r.status.replace("_", " ")}</div><RunCard run={r} events={events} streaming={stream} />{r.status === "waiting_human" && <InterruptCard run={r} botName={botName(r.actor_id)} />}</div></div>;
    })}
    {state.messages.length === 0 && active.length === 0 && <div className="empty-panel"><strong>Start a focused conversation.</strong><p>Say hello, ask for a plan, or mention a bot with <code>@handle</code>.</p></div>}
  </div>;
}
