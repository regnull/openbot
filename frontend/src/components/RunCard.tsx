import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Api } from "../api/client";
import { compact } from "../lib/threadUsage";
import type { Run, RunEvent } from "../api/types";
import { Badge, ErrorText } from "./ui";

const ACTIVE = ["queued", "running", "waiting_human"];

type Tone = "green" | "red" | "amber" | "blue";
const tone = (s: string): Tone => (s === "completed" ? "green" : s === "failed" || s === "cancelled" ? "red" : s === "waiting_human" ? "amber" : "blue");


/** "12.3k tok (78% cached)" — prompt + completion tokens over the run, with the cached share of the prompt. */
export function usageLabel(run: Pick<Run, "prompt_tokens" | "completion_tokens" | "cache_read_tokens" | "model_calls">): string | null {
  if (run.model_calls == null || run.prompt_tokens == null) return null;
  const total = run.prompt_tokens + (run.completion_tokens ?? 0);
  const cached = run.cache_read_tokens && run.prompt_tokens > 0 ? Math.round((run.cache_read_tokens / run.prompt_tokens) * 100) : 0;
  return `${compact(total)} tok${cached > 0 ? ` (${cached}% cached)` : ""} · ${run.model_calls} model call${run.model_calls === 1 ? "" : "s"}`;
}

export default function RunCard({ run, events, streaming }: { run: Run; events: RunEvent[]; streaming?: string }) {
  // Runs arrive as `queued` before they run, so "open while active" has to react to the
  // status changing, not just to its value at mount — otherwise a live card mounts
  // collapsed and hides the streaming text. A card the reader collapsed stays collapsed.
  const active = ACTIVE.includes(run.status);
  const [open, setOpen] = useState(active);
  const [collapsedByReader, setCollapsedByReader] = useState(false);
  const [wasActive, setWasActive] = useState(active);
  if (active !== wasActive) {
    setWasActive(active);
    if (active && !collapsedByReader) setOpen(true);
  }
  const toggle = () => { setCollapsedByReader(open); setOpen(!open); };
  // Nothing to invalidate: the cancel lands as a `run.updated` over SSE like any other status change.
  const cancel = useMutation({ mutationFn: () => Api.cancelRun(run.id) });
  // Events arrive sorted by seq; group contiguous text events and build a chronological list of content blocks.
  const results = new Map<unknown, RunEvent>(events.filter((e) => e.type === "tool_result").map((e) => [e.payload.tool_call_id, e] as const));
  /** Render a chronological transcript: text blocks interleaved with tool calls. */
  const body: React.ReactNode[] = [];
  for (const e of events) {
    if (e.type === "text") {
      const content: string = e.payload.content ?? "";
      if (content.trim()) {
        body.push(<pre key={e.id} className="whitespace-pre-wrap font-sans text-sm">{content}</pre>);
      }
    } else if (e.type === "tool_call") {
      const r = results.get(e.payload.id);
      const callId = e.payload.id ?? e.id;
      body.push(
        <details key={callId} className="rounded bg-white p-1 dark:bg-zinc-950">
          <summary className="cursor-pointer rounded px-1 py-0.5 font-mono leading-relaxed hover:bg-zinc-100 dark:hover:bg-zinc-900">
            <span className="text-zinc-700 dark:text-zinc-300">{e.payload.name}</span>
            <span className="break-words whitespace-pre-wrap text-zinc-600 dark:text-zinc-400">({JSON.stringify(e.payload.args)})</span>
          </summary>
          <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded border border-zinc-200 bg-zinc-50 p-2 font-mono text-[11px] leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">{r ? String(r.payload.content) : "…"}</pre>
        </details>
      );
    }
  }
  return (
    <div className="mt-1 rounded-md border border-zinc-200 bg-zinc-50 text-xs dark:border-zinc-800 dark:bg-zinc-900/60">
      <div className="flex items-center gap-2 px-2 py-1">
        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={toggle}>
          <Badge tone={tone(run.status)}>{run.status}</Badge>
          <span className="text-zinc-500">{events.filter((e) => e.type === "tool_call").length} tool call{events.filter((e) => e.type === "tool_call").length === 1 ? "" : "s"}</span>
          {usageLabel(run) && <span className="truncate text-zinc-500" title="prompt + completion tokens for this run">· {usageLabel(run)}</span>}
          <span className="ml-auto">{open ? "▾" : "▸"}</span>
        </button>
        {run.langsmith_run_id && (
          <a className="shrink-0 text-blue-600" target="_blank" rel="noreferrer" href={`https://smith.langchain.com/o/-/projects/p/-/r/${run.langsmith_run_id}`}>LangSmith ↗</a>
        )}
        {active && (
          <button
            className="shrink-0 rounded border border-zinc-300 px-1.5 py-0.5 text-zinc-600 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
          >
            {cancel.isPending ? "Cancelling…" : "Cancel"}
          </button>
        )}
      </div>
      {cancel.error && <div className="px-2 pb-1"><ErrorText error={cancel.error} /></div>}
      {open && (
        <div className="space-y-1 border-t border-zinc-200 p-2 dark:border-zinc-800">
          {body.length > 0 ? body : null}
          {run.error && <pre className="whitespace-pre-wrap text-red-600">{run.error}</pre>}
          {streaming && <pre className="whitespace-pre-wrap font-sans text-sm">{streaming}<span className="animate-pulse">▍</span></pre>}
          {body.length === 0 && !run.error && !streaming && <p className="text-zinc-500">No tool calls.</p>}
        </div>
      )}
    </div>
  );
}