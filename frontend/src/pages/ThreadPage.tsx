import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Api } from "../api/client";
import { useBusEvents } from "../api/sse";
import Composer from "../components/Composer";
import MessageList from "../components/MessageList";
import { Button, ErrorText, Spinner } from "../components/ui";
import { emptyThreadState, hydrate, mergeRun, reduceThreadEvent, type ThreadState } from "../lib/threadState";

export default function ThreadPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const detail = useQuery({ queryKey: ["thread", id], queryFn: () => Api.getThread(id) });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const [state, setState] = useState<ThreadState>(emptyThreadState());
  const [notice, setNotice] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  useEffect(() => { setState(emptyThreadState()); setHasMore(false); }, [id]);
  useEffect(() => { if (detail.data) { setState((s) => hydrate(s, detail.data)); setHasMore(detail.data.has_more); } }, [id, detail.data]);
  // Ack on open and whenever new messages land, so the inbox badge stays honest.
  useEffect(() => { Api.ackThread(id).then(() => qc.invalidateQueries({ queryKey: ["inbox"] })).catch(() => {}); }, [id, qc, state.messages.length]);
  useBusEvents(id, (e) => setState((s) => reduceThreadEvent(s, e)));
  const send = useMutation({
    mutationFn: (content: string) => Api.postMessage(id, { content }),
    onSuccess: (r) => setNotice(r.unaddressed ? "No bot was addressed. Mention a bot with @handle to wake it up." : null),
  });
  const loadOlder = useMutation({
    mutationFn: () => Api.getThread(id, state.messages[0].id),
    onSuccess: (older) => { setState((s) => hydrate(s, older)); setHasMore(older.has_more); },
  });
  const del = useMutation({ mutationFn: () => Api.deleteThread(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["threads"] }); nav("/threads"); } });
  if (detail.isLoading) return <Spinner />;
  if (!detail.data) return <ErrorText error={detail.error} />;
  const t = detail.data;
  const handles = [...new Set([
    ...t.participants.filter((p) => p.kind === "bot").map((p) => p.handle),
    ...(bots.data ?? []).filter((b) => b.enabled).map((b) => b.handle),
  ])];
  return (
    <div className="mx-auto flex h-[calc(100vh-3rem)] max-w-4xl flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-200 pb-3 dark:border-zinc-800">
        <Link to="/threads" className="text-sm text-zinc-500">← Threads</Link>
        <h1 className="truncate text-lg font-semibold">{t.title || "Untitled thread"}</h1>
        <div className="ml-auto truncate text-xs text-zinc-500">{t.participants.map((p) => `@${p.handle}`).join(" ")}</div>
        <Button variant="secondary" onClick={() => window.confirm("Delete thread?") && del.mutate()}>Delete</Button>
      </div>
      <div className="flex-1 overflow-y-auto py-4">
        {hasMore && state.messages.length > 0 && (
          <div className="mb-3 space-y-1 text-center">
            <Button variant="secondary" onClick={() => loadOlder.mutate()} disabled={loadOlder.isPending}>Load older</Button>
            <ErrorText error={loadOlder.error} />
          </div>
        )}
        <MessageList state={state} participants={t.participants} onRunLoaded={(run) => setState((s) => mergeRun(s, run))} />
      </div>
      <div className="border-t border-zinc-200 pt-3 dark:border-zinc-800">
        {notice && <p className="mb-1 text-xs text-amber-600">{notice}</p>}
        <ErrorText error={send.error} />
        <Composer handles={handles} onSend={async (text) => { await send.mutateAsync(text); }} />
      </div>
    </div>
  );
}
