import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Api } from "../api/client";
import type { BotInboxItem } from "../api/types";
import BotIcon from "../components/BotIcon";
import { Badge, Button, Card, ErrorText, Spinner, Textarea } from "../components/ui";
import { hasOpenItems, inboxRowState } from "../lib/botInbox";
import { parseTs } from "../lib/time";
import BotEditorPage from "./BotEditorPage";

const TABS = ["inbox", "memory", "settings"] as const;
type Tab = (typeof TABS)[number];

export default function BotPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "inbox";
  const bot = useQuery({ queryKey: ["bot", id], queryFn: () => Api.getBot(id) });
  if (bot.isLoading) return <Spinner />;
  if (!bot.data) return <ErrorText error={bot.error} />;
  const b = bot.data;
  const tabClass = (t: Tab) => `rounded-md px-3 py-1.5 text-sm ${tab === t ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"}`;
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center gap-3">
        <Link to="/bots" className="text-sm text-zinc-500">← Bots</Link>
        <BotIcon icon={b.icon} />
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{b.name} <span className="text-base font-normal text-zinc-500">@{b.handle}</span></h1>
          {b.description && <div className="truncate text-xs text-zinc-500">{b.description}</div>}
        </div>
        {b.active && <Badge tone="blue">active</Badge>}
        {!b.enabled && <Badge>disabled</Badge>}
      </div>
      <div className="flex gap-1 border-b border-zinc-200 pb-2 dark:border-zinc-800">
        {TABS.map((t) => <button key={t} type="button" className={tabClass(t)} onClick={() => setParams({ tab: t })}>{t[0].toUpperCase() + t.slice(1)}</button>)}
      </div>
      {tab === "inbox" && <InboxTab botId={id} />}
      {tab === "memory" && <MemoryTab botId={id} />}
      {tab === "settings" && <BotEditorPage />}
    </div>
  );
}

function InboxTab({ botId }: { botId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const inbox = useQuery({
    queryKey: ["bot-inbox", botId],
    queryFn: () => Api.getBotInbox(botId),
    // The event stream is per thread and an inbox spans many, so poll while anything is in flight.
    refetchInterval: (q) => (hasOpenItems(q.state.data ?? []) ? 3000 : false),
  });
  const post = useMutation({
    mutationFn: (content: string) => Api.postBotInbox(botId, content),
    onSuccess: () => { setText(""); qc.invalidateQueries({ queryKey: ["bot-inbox", botId] }); },
  });
  const send = () => { const c = text.trim(); if (c) post.mutate(c); };
  return (
    <div className="space-y-4">
      <Card className="space-y-2">
        <p className="text-xs text-zinc-500">Post straight to this bot. Each post is handled on its own: the bot sees only this message and its memories, not earlier posts.</p>
        <Textarea rows={3} value={text} placeholder="Message for the bot…" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }} />
        <div className="flex items-center gap-2">
          <Button onClick={send} disabled={post.isPending || !text.trim()}>{post.isPending ? "Sending…" : "Send"}</Button>
          <span className="text-xs text-zinc-500">⌘/Ctrl+Enter to send</span>
        </div>
        <ErrorText error={post.error} />
      </Card>
      <ErrorText error={inbox.error} />
      {inbox.isLoading && <Spinner />}
      {inbox.data?.length === 0 && <p className="text-sm text-zinc-500">Nothing in this inbox yet.</p>}
      {inbox.data?.map((item) => <InboxRow key={item.id} item={item} />)}
    </div>
  );
}

function InboxRow({ item }: { item: BotInboxItem }) {
  const state = inboxRowState(item);
  const from = item.message?.sender_name ?? (item.kind === "resume" ? "answer" : item.kind);
  return (
    <Card className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-zinc-500">
        <Badge tone={state.tone}>{state.label}</Badge>
        <span>{parseTs(item.created_at).toLocaleString()}</span>
        <span>· {item.thread_kind === "direct" ? "direct post" : <Link className="underline" to={`/threads/${item.thread_id}`}>from thread</Link>}</span>
        {state.open && <Spinner />}
      </div>
      <div className="whitespace-pre-wrap text-sm"><span className="text-zinc-500">{from}:</span> {item.message?.content ?? (item.kind === "resume" ? String(item.payload?.resume ?? "") : "")}</div>
      {item.reply && <div className="whitespace-pre-wrap rounded-md bg-zinc-50 p-2 text-sm dark:bg-zinc-950"><span className="text-zinc-500">{item.reply.sender_name}:</span> {item.reply.content}</div>}
      {item.last_error && <div className="text-xs text-red-600">{item.last_error}</div>}
    </Card>
  );
}

function MemoryTab({ botId }: { botId: string }) {
  const qc = useQueryClient();
  const memories = useQuery({ queryKey: ["bot-memories", botId], queryFn: () => Api.listBotMemories(botId) });
  const remove = useMutation({
    mutationFn: (key: string) => Api.deleteBotMemory(botId, key),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bot-memories", botId] }),
  });
  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-500">What this bot has learned about doing its job, shared across every thread it works in. Delete anything that is wrong or only true for one task.</p>
      <ErrorText error={memories.error ?? remove.error} />
      {memories.isLoading && <Spinner />}
      {memories.data?.length === 0 && <p className="text-sm text-zinc-500">No memories yet.</p>}
      {memories.data?.map((m) => (
        <Card key={m.key} className="flex items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="whitespace-pre-wrap text-sm">{m.content}</div>
            <div className="text-xs text-zinc-500">{m.updated_at ? parseTs(m.updated_at).toLocaleString() : ""}</div>
          </div>
          <Button variant="secondary" className="shrink-0" disabled={remove.isPending} onClick={() => confirm("Delete this memory?") && remove.mutate(m.key)}>Delete</Button>
        </Card>
      ))}
    </div>
  );
}
