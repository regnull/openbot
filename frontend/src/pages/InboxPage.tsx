import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Api } from "../api/client";
import { isBackendUnavailable } from "../api/errors";
import type { InboxItem, RunDetail } from "../api/types";
import InterruptCard from "../components/InterruptCard";
import { Button, Card, ErrorText, OfflineNotice, Spinner } from "../components/ui";
import { parseTs } from "../lib/time";

export default function InboxPage() {
  const qc = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: Api.listInbox });
  const questionIds = (inbox.data ?? []).filter((i) => i.kind === "question" && i.run_id).map((i) => i.run_id as string);
  // Backend down/restarting: show a friendly notice instead of the raw response body.
  const inboxUnavailable = isBackendUnavailable(inbox.error);
  const runs = useQuery({
    queryKey: ["inbox-runs", questionIds.join(",")],
    queryFn: async (): Promise<Record<string, RunDetail>> =>
      Object.fromEntries(await Promise.all(questionIds.map(async (id) => [id, await Api.getRun(id)] as const))),
    enabled: questionIds.length > 0,
  });
  const ack = useMutation({ mutationFn: (id: string) => Api.ackItem(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["inbox"] }) });
  const questions = inbox.data?.filter((i) => i.kind === "question") ?? [];
  const byThread = new Map<string, InboxItem[]>();
  inbox.data?.filter((i) => i.kind === "message").forEach((i) => {
    const tid = i.thread_id ?? "";
    byThread.set(tid, [...(byThread.get(tid) ?? []), i]);
  });
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Inbox</h1>
      {inboxUnavailable ? <OfflineNotice /> : <ErrorText error={inbox.error} />}
      {inbox.isLoading && <Spinner />}
      {questions.length > 0 && (
        <section className="space-y-3">
          <h2 className="font-medium">Waiting for you</h2>
          {questions.map((q) => {
            const run = q.run_id ? runs.data?.[q.run_id] : undefined;
            return (
              <Card key={q.id} className="space-y-2">
                <div className="text-xs text-zinc-500">
                  <Link className="underline" to={`/threads/${q.thread_id}`}>Open thread</Link> · {parseTs(q.created_at).toLocaleString()}
                </div>
                {run ? <InterruptCard run={run} onDone={() => qc.invalidateQueries({ queryKey: ["inbox-runs"] })} /> : <Spinner />}
              </Card>
            );
          })}
        </section>
      )}
      <section className="space-y-3">
        <h2 className="font-medium">Unread messages</h2>
        {byThread.size === 0 && !inbox.isLoading && <p className="text-sm text-zinc-500">All caught up.</p>}
        {[...byThread.entries()].map(([tid, items]) => (
          <Card key={tid} className="space-y-2">
            <div className="flex items-center justify-between">
              <Link to={`/threads/${tid}`} className="font-medium underline">{items.length} new message{items.length === 1 ? "" : "s"}</Link>
              <Button variant="secondary" onClick={() => items.forEach((i) => ack.mutate(i.id))}>Mark read</Button>
            </div>
            {items.slice(0, 3).map((i) => (
              <div key={i.id} className="truncate text-sm"><span className="text-zinc-500">{i.message?.sender_name}:</span> {i.message?.content}</div>
            ))}
          </Card>
        ))}
        <ErrorText error={ack.error} />
      </section>
    </div>
  );
}
