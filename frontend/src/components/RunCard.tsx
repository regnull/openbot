import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Api } from "../api/client";
import { compact } from "../lib/threadUsage";
import type { Run, RunEvent } from "../api/types";
import { Badge, Button, ErrorText, type BadgeTone } from "./ui";
import { ChevronDownIcon, ChevronRightIcon, ExternalIcon } from "./icons";

const ACTIVE = ["queued", "running", "waiting_human"];

const tone = (s: string): BadgeTone => (s === "completed" ? "green" : s === "failed" || s === "cancelled" ? "red" : s === "waiting_human" ? "amber" : "blue");


/** "12.3k tok (78% cached)" — prompt + completion tokens over the run, with the cached share of the prompt. */
export function usageLabel(run: Pick<Run, "prompt_tokens" | "completion_tokens" | "cache_read_tokens" | "model_calls">): string | null {
  if (run.model_calls == null || run.prompt_tokens == null) return null;
  const total = run.prompt_tokens + (run.completion_tokens ?? 0);
  const cached = run.cache_read_tokens && run.prompt_tokens > 0 ? Math.round((run.cache_read_tokens / run.prompt_tokens) * 100) : 0;
  return `${compact(total)} tok${cached > 0 ? ` (${cached}% cached)` : ""} · ${run.model_calls} model call${run.model_calls === 1 ? "" : "s"}`;
}

/**
 * The run log under a bot's message: what it said while working and every tool it called, as a
 * transcript. Tool calls read like shell lines — `$ name(args)` with the result folded beneath.
 */
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
  const toolCalls = events.filter((e) => e.type === "tool_call").length;
  /** Render a chronological transcript: text blocks interleaved with tool calls. */
  const body: React.ReactNode[] = [];
  for (const e of events) {
    if (e.type === "text") {
      const content: string = e.payload.content ?? "";
      if (content.trim()) {
        body.push(<pre key={e.id} className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-fg">{content}</pre>);
      }
    } else if (e.type === "tool_call") {
      const r = results.get(e.payload.id);
      const callId = e.payload.id ?? e.id;
      body.push(
        <details key={callId} className="group/call rounded-ui">
          <summary className="flex cursor-pointer list-none items-start gap-2 rounded-ui px-1.5 py-1 leading-relaxed hover:bg-sunken [&::-webkit-details-marker]:hidden">
            <span className="select-none text-accent" aria-hidden>$</span>
            <span className="min-w-0 flex-1 break-words">
              <span className="font-medium text-fg">{e.payload.name}</span>
              <span className="whitespace-pre-wrap text-muted">({JSON.stringify(e.payload.args)})</span>
            </span>
            <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 self-center rounded-full ${r ? "bg-ok" : "animate-pulse bg-warn"}`} title={r ? "returned" : "running"} aria-hidden />
          </summary>
          <pre className="ml-3.5 mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-ui border border-line bg-canvas p-2 text-[11px] leading-relaxed text-muted scrollbar-subtle">{r ? String(r.payload.content) : "…"}</pre>
        </details>
      );
    }
  }
  return (
    <div className="mt-2 rounded-ui border border-line bg-sunken/50 text-xs">
      <div className="flex min-h-8 items-center gap-2 px-2 py-1">
        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={toggle} aria-expanded={open}>
          {open ? <ChevronDownIcon className="h-3.5 w-3.5 shrink-0 text-faint" /> : <ChevronRightIcon className="h-3.5 w-3.5 shrink-0 text-faint" />}
          <Badge tone={tone(run.status)} pulse={run.status === "running"}>{run.status.replace("_", " ")}</Badge>
          <span className="whitespace-nowrap text-muted">{toolCalls} tool call{toolCalls === 1 ? "" : "s"}</span>
          {usageLabel(run) && <span className="hidden truncate text-faint sm:inline" title="prompt + completion tokens for this run">{usageLabel(run)}</span>}
        </button>
        {run.langsmith_run_id && (
          <a className="inline-flex shrink-0 items-center gap-1 text-muted hover:text-fg" target="_blank" rel="noreferrer" href={`https://smith.langchain.com/o/-/projects/p/-/r/${run.langsmith_run_id}`}>LangSmith <ExternalIcon className="h-3 w-3" /></a>
        )}
        {active && (
          <Button variant="secondary" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            {cancel.isPending ? "Cancelling…" : "Cancel"}
          </Button>
        )}
      </div>
      {cancel.error && <div className="px-2 pb-1"><ErrorText error={cancel.error} /></div>}
      {open && (
        <div className="space-y-1 border-t border-line p-2">
          {body.length > 0 ? body : null}
          {run.error && <pre className="whitespace-pre-wrap rounded-ui border border-danger/30 bg-danger/5 p-2 text-danger">{run.error}</pre>}
          {streaming && <pre className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-fg">{streaming}<span className="caret ml-0.5" aria-hidden /></pre>}
          {body.length === 0 && !run.error && !streaming && <p className="px-1.5 text-faint">No tool calls.</p>}
        </div>
      )}
    </div>
  );
}
