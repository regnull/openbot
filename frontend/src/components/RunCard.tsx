import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Api } from "../api/client";
import { usageLabel } from "../lib/usageLabel";
import type { Run, RunEvent } from "../api/types";
import { Badge, Button, Dialog, ErrorText, IconButton, type BadgeTone } from "./ui";
import { ChevronDownIcon, ChevronRightIcon, ExternalIcon, NotepadIcon } from "./icons";

const ACTIVE = ["queued", "running", "waiting_human"];

const tone = (s: string): BadgeTone => (s === "completed" ? "green" : s === "failed" || s === "cancelled" ? "red" : s === "waiting_human" ? "amber" : "blue");

/**
 * The run log under a bot's message: what it said while working and every tool it called, as a
 * transcript. Tool calls read like shell lines — `$ name(args)` with the result folded beneath.
 */
export default function RunCard({ run, events, streaming, botName }: { run: Run; events: RunEvent[]; streaming?: string; botName?: string | null }) {
  // Always collapsed by default regardless of run status; the user clicks to expand.
  const active = ACTIVE.includes(run.status);
  const [open, setOpen] = useState(false);
  const toggle = () => setOpen((o) => !o);
  // Nothing to invalidate: the cancel lands as a `run.updated` over SSE like any other status change.
  const cancel = useMutation({ mutationFn: () => Api.cancelRun(run.id) });
  // The bot's persistent scratchpad. It is per bot, so every card of the same bot shares one
  // query; the header shows an icon for it only when there is something saved.
  const qc = useQueryClient();
  const pad = useQuery({ queryKey: ["bot-scratchpad", run.actor_id], queryFn: () => Api.getBotScratchpad(run.actor_id), staleTime: 30_000, retry: false });
  const [padOpen, setPadOpen] = useState(false);
  const openScratchpad = () => {
    setPadOpen(true);
    void pad.refetch(); // show the latest write, not the cached copy
  };
  // A scratchpad save landing in this run changes the pad: refetch it. Only saves that arrive while
  // the card is mounted count — a thread full of old runs must not each refetch on mount.
  const padSaves = events.filter((e) => e.type === "tool_result" && e.payload.name === "scratchpad").length;
  const seenPadSaves = useRef(padSaves);
  useEffect(() => {
    if (padSaves > seenPadSaves.current) qc.invalidateQueries({ queryKey: ["bot-scratchpad", run.actor_id] });
    seenPadSaves.current = padSaves;
  }, [padSaves, qc, run.actor_id]);
  const padText = pad.data?.content ?? "";
  // Events arrive sorted by seq; group contiguous text events and build a chronological list of content blocks.
  const results = new Map<unknown, RunEvent>(events.filter((e) => e.type === "tool_result").map((e) => [e.payload.tool_call_id, e] as const));
  const toolCalls = events.filter((e) => e.type === "tool_call").length;
  const failed = [...results.values()].filter((r) => r.payload.status === "error").length;
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
            <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 self-center rounded-full ${!r ? "animate-pulse bg-warn" : r.payload.status === "error" ? "bg-danger" : "bg-ok"}`} title={!r ? "running" : r.payload.status === "error" ? "failed" : "returned"} aria-hidden />
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
          <span className="whitespace-nowrap text-muted">{toolCalls} tool call{toolCalls === 1 ? "" : "s"}{failed > 0 && <span className="text-danger"> · {failed} failed</span>}</span>
          {usageLabel(run) && <span className="hidden truncate text-faint sm:inline" title="prompt + completion tokens for this run">{usageLabel(run)}</span>}
        </button>
        {run.langsmith_run_id && (
          <a className="inline-flex shrink-0 items-center gap-1 text-muted hover:text-fg" target="_blank" rel="noreferrer" href={`https://smith.langchain.com/o/-/projects/p/-/r/${run.langsmith_run_id}`}>LangSmith <ExternalIcon className="h-3 w-3" /></a>
        )}
        {padText.trim() && (
          <IconButton size="sm" className="-mx-1 h-6 w-6" onClick={openScratchpad} aria-label="Show scratchpad" title={botName ? `${botName}'s scratchpad` : "Scratchpad"}>
            <NotepadIcon className="h-3.5 w-3.5" />
          </IconButton>
        )}
        {active && (
          <Button variant="secondary" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            {cancel.isPending ? "Cancelling…" : "Cancel"}
          </Button>
        )}
      </div>
      {cancel.error && <div className="px-2 pb-1"><ErrorText error={cancel.error} /></div>}
      {padOpen && (
        <Dialog title={botName ? `${botName}'s scratchpad` : "Scratchpad"} titleId={`scratchpad-${run.id}`} onClose={() => setPadOpen(false)} className="max-w-2xl gap-3">
          {pad.data?.updated_at && <p className="-mt-2 text-xs text-faint">updated {new Date(pad.data.updated_at).toLocaleString()}</p>}
          {pad.error && <ErrorText error={pad.error} />}
          {padText.trim()
            ? <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-ui border border-line bg-canvas p-3 text-xs leading-relaxed text-fg scrollbar-subtle">{padText}</pre>
            : !pad.error && <p className="text-xs text-faint">Scratchpad is empty.</p>}
        </Dialog>
      )}
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
