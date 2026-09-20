import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Api } from "../api/client";
import { isBackendUnavailable } from "../api/errors";
import type { InboxItem, RunDetail } from "../api/types";
import InterruptCard from "../components/InterruptCard";
import { Button, Card, EmptyState, ErrorText, OfflineNotice, PageTitle, SectionTitle, Spinner } from "../components/ui";
import { parseTs } from "../lib/time";

export default function InboxPage() {
  const qc = useQueryClient();
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: Api.listInbox });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const botName = (actorId: string) => bots.data?.find((b) => b.id === actorId)?.name;
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
      <PageTitle>Inbox</PageTitle>
      {inboxUnavailable ? <OfflineNotice /> : <ErrorText error={inbox.error} />}
      {inbox.isLoading && <Spinner />}
      {questions.length > 0 && (
        <section className="space-y-3">
          <SectionTitle>Waiting for you</SectionTitle>
          {questions.map((q) => {
            const run = q.run_id ? runs.data?.[q.run_id] : undefined;
            return (
              <Card key={q.id} className="space-y-2">
                <div className="flex items-center gap-3 text-[11px] text-muted">
                  <Link className="hover:text-fg hover:underline" to={`/threads/${q.thread_id}`}>Open thread</Link>
                  <time className="text-faint" dateTime={q.created_at}>{parseTs(q.created_at).toLocaleString()}</time>
                </div>
                {run ? <InterruptCard run={run} botName={botName(run.actor_id)} onDone={() => qc.invalidateQueries({ queryKey: ["inbox-runs"] })} /> : <Spinner />}
              </Card>
            );
          })}
        </section>
      )}
      <section className="space-y-3">
        <SectionTitle>Unread messages</SectionTitle>
        {byThread.size === 0 && !inbox.isLoading && (
          <EmptyState>All caught up. Replies and questions from your bots land here as they arrive.</EmptyState>
        )}
        {[...byThread.entries()].map(([tid, items]) => (
          <Card key={tid} className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Link to={`/threads/${tid}`} className="text-[13px] font-medium hover:underline">{items.length} new message{items.length === 1 ? "" : "s"}</Link>
              <Button variant="secondary" size="sm" onClick={() => items.forEach((i) => ack.mutate(i.id))}>Mark read</Button>
            </div>
            <div className="space-y-1">
              {items.slice(0, 3).map((i) => (
                <div key={i.id} className="truncate font-sans text-[13px]"><span className="font-mono text-xs text-muted">{i.message?.sender_name}</span> <span className="text-fg/90">{i.message?.content}</span></div>
              ))}
              {items.length > 3 && <div className="text-[11px] text-faint">and {items.length - 3} more</div>}
            </div>
          </Card>
        ))}
        <ErrorText error={ack.error} />
      </section>
    </div>
  );
}
