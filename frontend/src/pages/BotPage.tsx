import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Api } from "../api/client";
import type { BotInboxItem } from "../api/types";
import BotIcon from "../components/BotIcon";
import { Badge, Button, Card, EmptyState, ErrorText, Hint, Kbd, Spinner, Textarea } from "../components/ui";
import { ChevronLeftIcon } from "../components/icons";
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
  const tabClass = (t: Tab) => `relative -mb-px h-9 px-1 text-[13px] transition-colors ${tab === t ? "border-b-2 border-accent font-medium text-fg" : "border-b-2 border-transparent text-muted hover:text-fg"}`;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center gap-3">
        <Link to="/bots" aria-label="Back to bots" title="Bots" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-ui text-muted hover:bg-sunken hover:text-fg"><ChevronLeftIcon className="h-4 w-4" /></Link>
        <BotIcon icon={b.icon} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-semibold tracking-tight">{b.name} <span className="text-sm font-normal text-muted">@{b.handle}</span></h1>
          {b.description && <div className="truncate font-sans text-xs text-muted">{b.description}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {b.active && <Badge tone="green" pulse>active</Badge>}
          {!b.enabled && <Badge tone="amber">disabled</Badge>}
        </div>
      </div>
      <div className="flex gap-5 border-b border-line" role="tablist">
        {TABS.map((t) => <button key={t} type="button" role="tab" aria-selected={tab === t} className={tabClass(t)} onClick={() => setParams({ tab: t })}>{t[0].toUpperCase() + t.slice(1)}</button>)}
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
      <Card className="space-y-3">
        <Hint>Post straight to this bot. Each post is handled on its own: the bot sees only this message and its memories, not earlier posts.</Hint>
        <Textarea rows={3} value={text} placeholder="Message for the bot" aria-label="Message for the bot" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }} />
        <div className="flex items-center gap-3">
          <Button onClick={send} disabled={post.isPending || !text.trim()}>{post.isPending ? "Sending…" : "Send"}</Button>
          <span className="inline-flex items-center gap-1 text-[11px] text-faint"><Kbd>⌘⏎</Kbd> send</span>
        </div>
        <ErrorText error={post.error} />
      </Card>
      <ErrorText error={inbox.error} />
      {inbox.isLoading && <Spinner />}
      {inbox.data?.length === 0 && <EmptyState>Nothing in this inbox yet. Posts to this bot and mentions from threads show up here.</EmptyState>}
      {inbox.data?.map((item) => <InboxRow key={item.id} item={item} />)}
    </div>
  );
}

function InboxRow({ item }: { item: BotInboxItem }) {
  const state = inboxRowState(item);
  const from = item.message?.sender_name ?? (item.kind === "resume" ? "answer" : item.kind);
  return (
    <Card className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
        <Badge tone={state.tone} pulse={state.open}>{state.label}</Badge>
        <time className="text-faint" dateTime={item.created_at}>{parseTs(item.created_at).toLocaleString()}</time>
        <span>{item.thread_kind === "direct" ? "direct post" : <Link className="hover:text-fg hover:underline" to={`/threads/${item.thread_id}`}>from thread</Link>}</span>
        {state.open && <Spinner />}
      </div>
      <div className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed"><span className="font-mono text-xs text-muted">{from} </span>{item.message?.content ?? (item.kind === "resume" ? String(item.payload?.resume ?? "") : "")}</div>
      {item.reply && <div className="whitespace-pre-wrap rounded-ui border-l-2 border-line bg-sunken/60 px-3 py-2 font-sans text-[13px] leading-relaxed"><span className="font-mono text-xs text-muted">{item.reply.sender_name} </span>{item.reply.content}</div>}
      {item.last_error && <div className="text-xs text-danger">{item.last_error}</div>}
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
      <Hint>What this bot has learned about doing its job, shared across every thread it works in. Delete anything that is wrong or only true for one task.</Hint>
      <ErrorText error={memories.error ?? remove.error} />
      {memories.isLoading && <Spinner />}
      {memories.data?.length === 0 && <EmptyState>No memories yet. They accumulate as the bot works.</EmptyState>}
      {memories.data?.map((m) => (
        <Card key={m.key} className="flex items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed">{m.content}</div>
            <div className="text-[11px] text-faint">{m.updated_at ? parseTs(m.updated_at).toLocaleString() : ""}</div>
          </div>
          <Button variant="secondary" size="sm" disabled={remove.isPending} onClick={() => confirm("Delete this memory?") && remove.mutate(m.key)}>Delete</Button>
        </Card>
      ))}
    </div>
  );
}
