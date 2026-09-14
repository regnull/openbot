import { useState } from "react";
import type { Run, RunEvent } from "../api/types";
import { Badge } from "./ui";

type Tone = "green" | "red" | "amber" | "blue";
const tone = (s: string): Tone => (s === "completed" ? "green" : s === "failed" || s === "cancelled" ? "red" : s === "waiting_human" ? "amber" : "blue");

export default function RunCard({ run, events, streaming }: { run: Run; events: RunEvent[]; streaming?: string }) {
  const [open, setOpen] = useState(run.status === "running");
  const calls = events.filter((e) => e.type === "tool_call");
  const results = new Map<unknown, RunEvent>(events.filter((e) => e.type === "tool_result").map((e) => [e.payload.tool_call_id, e] as const));
  return (
    <div className="mt-1 rounded-md border border-zinc-200 bg-zinc-50 text-xs dark:border-zinc-800 dark:bg-zinc-900/60">
      <div className="flex items-center gap-2 px-2 py-1">
        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen((o) => !o)}>
          <Badge tone={tone(run.status)}>{run.status}</Badge>
          <span className="text-zinc-500">{calls.length} tool call{calls.length === 1 ? "" : "s"}</span>
          <span className="ml-auto">{open ? "▾" : "▸"}</span>
        </button>
        {run.langsmith_run_id && (
          <a className="shrink-0 text-blue-600" target="_blank" rel="noreferrer" href={`https://smith.langchain.com/o/-/projects/p/-/r/${run.langsmith_run_id}`}>LangSmith ↗</a>
        )}
      </div>
      {open && (
        <div className="space-y-1 border-t border-zinc-200 p-2 dark:border-zinc-800">
          {calls.map((c) => {
            const r = results.get(c.payload.id);
            return (
              <details key={c.id} className="rounded bg-white p-1 dark:bg-zinc-950">
                <summary className="cursor-pointer font-mono">{c.payload.name}({JSON.stringify(c.payload.args)})</summary>
                <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-zinc-600 dark:text-zinc-400">{r ? String(r.payload.content) : "…"}</pre>
              </details>
            );
          })}
          {run.error && <pre className="whitespace-pre-wrap text-red-600">{run.error}</pre>}
          {streaming && <pre className="whitespace-pre-wrap font-sans text-sm">{streaming}<span className="animate-pulse">▍</span></pre>}
          {!calls.length && !run.error && !streaming && <p className="text-zinc-500">No tool calls.</p>}
        </div>
      )}
    </div>
  );
}
