import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Api } from "../api/client";

export default function ScheduledPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["scheduled"], queryFn: Api.listScheduled });
  const threads = useQuery({ queryKey: ["threads"], queryFn: Api.listThreads });
  const [threadId, setThreadId] = useState("");
  const [content, setContent] = useState("");
  const [when, setWhen] = useState(2);
  const cancel = useMutation({ mutationFn: Api.cancelScheduled, onSuccess: () => qc.invalidateQueries({ queryKey: ["scheduled"] }) });
  const create = useMutation({ mutationFn: Api.createScheduled, onSuccess: () => { setContent(""); qc.invalidateQueries({ queryKey: ["scheduled"] }); } });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!threadId || !content.trim() || when < 1) return;
    create.mutate({ thread_id: threadId, content: content.trim(), due_at: new Date(Date.now() + when * 60_000).toISOString(), to: [] });
  };
  return <main className="mx-auto max-w-4xl p-4 sm:p-6" aria-labelledby="scheduled-title">
    <h1 id="scheduled-title" className="text-2xl font-semibold">Scheduled messages</h1>
    <p className="mt-1 text-sm text-muted">Create one-shot messages and inspect every outcome.</p>
    <form onSubmit={submit} className="mt-6 rounded-ui border border-line p-4" aria-label="Create scheduled message">
      <label className="block text-sm font-medium" htmlFor="schedule-thread">Thread</label>
      <select id="schedule-thread" className="mt-1 w-full rounded-ui border border-line bg-surface p-2" value={threadId} onChange={e => setThreadId(e.target.value)} required>
        <option value="">Choose a thread</option>{threads.data?.map(t => <option key={t.id} value={t.id}>{t.title || t.id}</option>)}
      </select>
      <label className="mt-3 block text-sm font-medium" htmlFor="schedule-content">Message</label>
      <textarea id="schedule-content" className="mt-1 min-h-20 w-full rounded-ui border border-line bg-surface p-2" value={content} onChange={e => setContent(e.target.value)} required maxLength={20000} />
      <label className="mt-3 block text-sm font-medium" htmlFor="schedule-minutes">Send after (minutes)</label>
      <input id="schedule-minutes" type="number" min="1" max="525600" className="mt-1 w-full rounded-ui border border-line bg-surface p-2" value={when} onChange={e => setWhen(Number(e.target.value))} required />
      <button className="mt-4 rounded-ui bg-accent px-4 py-2 text-sm text-white disabled:opacity-50" disabled={create.isPending}>Schedule</button>
      {create.isError && <p role="alert" className="mt-2 text-sm text-danger">Unable to schedule message.</p>}
    </form>
    <div className="mt-6 space-y-2">{q.data?.map(j => <article key={j.id} className="rounded-ui border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>{j.status}</strong><time dateTime={j.due_at}>{new Date(j.due_at).toLocaleString()}</time></div>
      <p className="mt-2 whitespace-pre-wrap">{j.content}</p><p className="mt-1 text-xs text-muted">Thread {j.thread_id} · attempts {j.attempts}</p>
      {j.last_error && <p className="mt-2 text-sm text-danger">{j.last_error}</p>}
      {j.status === "pending" && <button className="mt-3 rounded-ui border border-line px-3 py-1 text-sm" onClick={() => cancel.mutate(j.id)}>Cancel</button>}
    </article>)}</div>
  </main>;
}
