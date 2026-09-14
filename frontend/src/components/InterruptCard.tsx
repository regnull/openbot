import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Api } from "../api/client";
import type { Run } from "../api/types";
import { Button, ErrorText, Input } from "./ui";

type Decision = "approve" | "reject";

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
    <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950/40">
      <div className="font-medium">{botName ?? "Bot"} is waiting for you</div>
      {it.kind === "question" ? (
        <>
          <p className="whitespace-pre-wrap">{it.question}</p>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); resume.mutate({ answer }); }}>
            <Input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer" />
            <Button type="submit" disabled={resume.isPending || !answer.trim()}>Answer</Button>
          </form>
        </>
      ) : (
        <>
          {it.actions?.map((a, i) => (
            <div key={i} className="flex items-center gap-2 rounded border border-amber-200 bg-white/60 p-2 font-mono text-xs dark:border-amber-800 dark:bg-black/20">
              <span className="flex-1 truncate">{a.name}({JSON.stringify(a.args)})</span>
              {(["approve", "reject"] as const).map((d) => (
                <label key={d} className="flex items-center gap-1">
                  <input type="radio" checked={(decisions[i] ?? "approve") === d} onChange={() => setDecisions((ds) => ({ ...ds, [i]: d }))} />
                  {d}
                </label>
              ))}
            </div>
          ))}
          <Button onClick={() => resume.mutate({ decisions: decisionsFor(it.actions?.length ?? 0) })} disabled={resume.isPending}>Submit decisions</Button>
        </>
      )}
      <ErrorText error={resume.error} />
    </div>
  );
}
