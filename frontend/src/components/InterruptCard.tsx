import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Api } from "../api/client";
import type { Run } from "../api/types";
import MarkdownContent from "./MarkdownContent";
import { Button, ErrorText, Input } from "./ui";

type Decision = "approve" | "reject";

/** A bot has stopped and needs a person: a question to answer, or tool calls to approve. */
export default function InterruptCard({ run, botName, onDone }: { run: Run; botName?: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const [answer, setAnswer] = useState("");
  // Keyed by action index; a run can raise a second, differently shaped approval
  // interrupt without remounting, so treat a missing entry as "approve".
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const decisionsFor = (n: number): Decision[] => Array.from({ length: n }, (_, i) => decisions[i] ?? "approve");
  const resume = useMutation({
    mutationFn: (body: { answer?: string; decisions?: Decision[] }) => Api.resumeRun(run.id, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["inbox"] }); onDone?.(); },
  });
  if (!run.interrupt) return null;
  const it = run.interrupt;
  return (
    <div className="mt-2 space-y-3 rounded-ui border border-warn/50 border-l-2 border-l-warn bg-warn/[0.06] p-3 text-[13px]">
      <div className="flex items-center gap-2 text-xs font-medium text-warn">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warn" aria-hidden />
        {botName ?? "Bot"} is waiting for you
      </div>
      {it.kind === "question" ? (
        <>
          <MarkdownContent content={it.question ?? ""} />
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); resume.mutate({ answer }); }}>
            <Input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer" aria-label="Your answer" />
            <Button type="submit" disabled={resume.isPending || !answer.trim()}>Answer</Button>
          </form>
        </>
      ) : (
        <>
          <p className="font-sans text-muted">Review each tool call before the bot runs it.</p>
          <div className="space-y-1.5">
            {it.actions?.map((a, i) => {
              const d = decisions[i] ?? "approve";
              return (
                <div key={i} className="flex items-center gap-3 rounded-ui border border-line bg-surface px-2 py-1.5 text-xs">
                  <span className="select-none text-accent" aria-hidden>$</span>
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium">{a.name}</span><span className="text-muted">({JSON.stringify(a.args)})</span></span>
                  <div role="radiogroup" aria-label={`Decision for ${a.name}`} className="inline-flex shrink-0 rounded-ui border border-line p-0.5">
                    {(["approve", "reject"] as const).map((opt) => (
                      <button key={opt} type="button" role="radio" aria-checked={d === opt} onClick={() => setDecisions((ds) => ({ ...ds, [i]: opt }))}
                        className={`h-6 rounded-[2px] px-2 text-[11px] transition-colors ${d === opt ? (opt === "approve" ? "bg-ok/15 text-ok" : "bg-danger/15 text-danger") : "text-faint hover:text-muted"}`}>
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <Button onClick={() => resume.mutate({ decisions: decisionsFor(it.actions?.length ?? 0) })} disabled={resume.isPending}>Submit decisions</Button>
        </>
      )}
      <ErrorText error={resume.error} />
    </div>
  );
}
