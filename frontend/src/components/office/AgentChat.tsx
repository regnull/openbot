import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import type { AgentId } from "../../lib/office/agents";
import { MAX_MESSAGE_LENGTH, QUICK_TASKS, type MessageCheck } from "../../lib/office/conversation";
import type { ChatMessage, MockAgentTask, UserTaskPhase } from "../../lib/office/simulation";
import { Badge, type BadgeTone } from "../ui";
import type { ChatView } from "./OfficeViewer";

const NAVY = "#16213E";
const PHASE: Record<UserTaskPhase, { label: string; tone: BadgeTone }> = {
  queued: { label: "queued", tone: "zinc" },
  assigned: { label: "assigned", tone: "blue" },
  in_progress: { label: "in progress", tone: "blue" },
  blocked: { label: "blocked", tone: "red" },
  reporting: { label: "reporting", tone: "amber" },
  completed: { label: "done", tone: "green" },
  cancelled: { label: "set aside", tone: "zinc" },
};
const ACTIVE: UserTaskPhase[] = ["assigned", "in_progress", "blocked", "reporting"];
/** Pause before an agent's new line appears (a typing beat; purely presentational). */
const REPLY_BEAT_MS = 420;

/** Role glyphs for the avatar (24-unit stroke icons). */
const ROLE_ICON: Record<AgentId, ReactNode> = {
  commander: <path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z" />,
  coder: <path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5" />,
  researcher: <><circle cx="10.5" cy="10.5" r="5.5" /><path d="M15 15l5 5" /></>,
  tester: <><path d="M4 7l2 2 3.5-3.5M4 15l2 2 3.5-3.5" /><path d="M13 8h7M13 16h7" /></>,
  ops: <path d="M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.5 2.5-2.5-.5-.5-2.5z" />,
  reporter: <path d="M5 20V11M10 20V5M15 20v-7M20 20V9" />,
  worker1: <><rect x="4" y="5" width="16" height="11" rx="1.5" /><path d="M2.5 19h19" /></>,
  worker2: <><rect x="4" y="5" width="16" height="11" rx="1.5" /><path d="M2.5 19h19" /></>,
};

function Avatar({ agent, size = 36 }: { agent: AgentId; size?: number }) {
  return (
    <span aria-hidden className="inline-flex shrink-0 items-center justify-center rounded-full border-2 border-[#38d6f5] bg-[#f6f4ef] text-[#16213E]" style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" width={size * 0.5} height={size * 0.5} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        {ROLE_ICON[agent]}
      </svg>
    </span>
  );
}

function Typing({ name, waving }: { name: string; waving: boolean }) {
  return (
    <li className="flex items-center gap-2 px-1 text-[11px] text-muted" aria-live="polite">
      <span className="inline-flex gap-1 rounded-2xl rounded-bl-md bg-sunken px-3 py-2" aria-hidden>
        {[0, 1, 2].map((i) => <span key={i} className="thinking-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: `${i * 0.16}s` }} />)}
      </span>
      <span>{waving ? `${name} is waving hello…` : `${name} is typing…`}</span>
    </li>
  );
}

function Proposal({ m, busy, onAnswer }: { m: ChatMessage; busy: boolean; onAnswer: (action: "assign" | "replace" | "dismiss") => void }) {
  const p = m.proposal!;
  if (p.status !== "open") {
    const done = { assigned: "Assigned", queued: "Added to the queue", replaced: "Switched to this task", dismissed: "Not assigned", open: "" }[p.status];
    return <p className="mt-1.5 text-[11px] text-muted">{done}</p>;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <button type="button" onClick={() => onAnswer("assign")}
        className="h-7 rounded-full bg-[#16213E] px-3 text-xs font-medium text-white transition-colors hover:bg-[#24335c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]">
        {busy ? "Add to queue" : "Assign task"}
      </button>
      {busy && (
        <button type="button" onClick={() => onAnswer("replace")}
          className="h-7 rounded-full border border-[#16213E]/30 px-3 text-xs text-fg transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]">
          Do it now
        </button>
      )}
      <button type="button" onClick={() => onAnswer("dismiss")}
        className="h-7 rounded-full px-2.5 text-xs text-muted transition-colors hover:bg-surface hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]">
        Not now
      </button>
    </div>
  );
}

function Message({ m, busy, onAnswer }: { m: ChatMessage; busy: boolean; onAnswer: (id: string, action: "assign" | "replace" | "dismiss") => void }) {
  if (m.from === "user") {
    return (
      <li className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md px-3 py-2 text-[13px] leading-snug text-white" style={{ background: NAVY }}>{m.text}</p>
      </li>
    );
  }
  if (m.kind === "info") {
    return <li className="px-2 text-center text-[11px] leading-snug text-muted">{m.text}</li>;
  }
  return (
    <li className="flex">
      <div className={`max-w-[88%] rounded-2xl rounded-bl-md bg-sunken px-3 py-2 text-[13px] leading-snug text-fg ${m.kind === "result" ? "border-l-[3px] border-[#38d6f5]" : ""}`}>
        {m.kind === "result" && <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-info">Demo result</p>}
        <p className="whitespace-pre-wrap break-words">{m.text}</p>
        {m.proposal && <Proposal m={m} busy={busy} onAnswer={(a) => onAnswer(m.id, a)} />}
      </div>
    </li>
  );
}

function TaskStrip({ tasks }: { tasks: MockAgentTask[] }) {
  const active = tasks.find((t) => ACTIVE.includes(t.status));
  const queued = tasks.filter((t) => t.status === "queued").reverse();
  const last = !active ? tasks.find((t) => t.status === "completed") : undefined;
  if (!active && !queued.length && !last) return null;
  return (
    <div className="space-y-1.5 border-b border-line bg-surface px-3 py-2">
      {[active ?? last].filter(Boolean).map((t) => (
        <div key={t!.id}>
          <div className="flex items-center justify-between gap-2">
            <p className="min-w-0 truncate text-xs font-medium" title={t!.title}>{t!.title}</p>
            <Badge tone={PHASE[t!.status].tone} pulse={t!.status === "blocked"}>{PHASE[t!.status].label}</Badge>
          </div>
          {t!.status !== "completed" && (
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-label={`${t!.title} progress`}
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(t!.progress * 100)}>
              <div className="h-full rounded-full bg-[#38d6f5] transition-[width] duration-300" style={{ width: `${Math.round(t!.progress * 100)}%` }} />
            </div>
          )}
        </div>
      ))}
      {queued.length > 0 && (
        <p className="truncate text-[11px] text-muted">Next: {queued.map((t) => t.title).join(" · ")}</p>
      )}
    </div>
  );
}

/**
 * Conversation with the selected Openling. Replies and tasks are local demo simulations (no model,
 * no backend); all text is rendered as plain text. Mount it with `key={chat.agent}`: each agent's
 * chat starts fresh (history already there shows at once, new lines after a short typing beat).
 */
export function AgentChat({ chat, onSend, onAnswer, onQuick, onSayHi, onClose, canGreet }: {
  chat: ChatView;
  onSend: (text: string) => MessageCheck | null;
  onAnswer: (messageId: string, action: "assign" | "replace" | "dismiss") => void;
  onQuick: (quickId: string) => void;
  onSayHi: () => void;
  onClose: () => void;
  /** The simulation runs (a paused office does not wave). */
  canGreet: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(false);
  const [shown, setShown] = useState(false);
  const listRef = useRef<HTMLOListElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const timers = useRef<number[]>([]);
  const [initial] = useState(() => new Set(chat.messages.map((m) => m.id)));
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(() => new Set());
  const scheduled = useRef(new Set<string>());

  useEffect(() => {
    let k = 0;
    for (const m of chat.messages) {
      if (m.from === "user" || initial.has(m.id) || scheduled.current.has(m.id)) continue;
      scheduled.current.add(m.id);
      const id = m.id;
      timers.current.push(window.setTimeout(() => setRevealed((prev) => new Set(prev).add(id)), REPLY_BEAT_MS * ++k));
    }
  }, [chat.messages, initial]);

  useEffect(() => () => { timers.current.forEach(clearTimeout); timers.current = []; }, []);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setShown(true));
    if (window.matchMedia?.("(min-width: 768px)").matches) inputRef.current?.focus({ preventScroll: true });
    return () => cancelAnimationFrame(raf);
  }, []);

  const waving = chat.interaction === "greeting";
  const ready = (m: ChatMessage) => m.from === "user" || initial.has(m.id) || revealed.has(m.id);
  const visible = chat.messages.filter((m) => ready(m) && !(m.kind === "greeting" && waving));
  const typing = chat.messages.some((m) => !ready(m)) || (waving && chat.messages.some((m) => m.kind === "greeting"));
  const busy = chat.tasks.some((t) => ACTIVE.includes(t.status));

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [visible.length, typing]);

  const close = () => {
    setShown(false);
    timers.current.push(window.setTimeout(onClose, 160));
  };

  const send = () => {
    const r = onSend(draft);
    if (!r) return;
    if (r.ok) {
      setDraft("");
      setError(null);
    } else {
      setError(r.reason === "too_long" ? `Keep it under ${MAX_MESSAGE_LENGTH} characters.` : "Type a message first.");
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (draft.trim()) send();
    }
  };

  const quick = (id: string) => {
    if (cooldown) return;
    setCooldown(true);
    timers.current.push(window.setTimeout(() => setCooldown(false), 700));
    onQuick(id);
  };

  return (
    <section
      aria-label={`Chat with ${chat.name}`}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}
      className={`absolute inset-x-2 bottom-2 z-20 flex h-[64%] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-[0_12px_40px_rgba(22,33,62,0.22)] transition-[opacity,transform] duration-200 ease-out md:inset-x-auto md:bottom-3 md:right-3 md:top-3 md:h-auto md:w-[min(360px,42%)] ${shown ? "translate-y-0 opacity-100 md:translate-x-0" : "translate-y-3 opacity-0 md:translate-x-3 md:translate-y-0"}`}
    >
      <header className="flex items-center gap-2.5 px-3 py-2.5 text-white" style={{ background: NAVY }}>
        <Avatar agent={chat.agent} />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold leading-tight">{chat.name}</h2>
          <p className="flex items-center gap-1.5 truncate text-[11px] text-white/75">
            <span>{chat.role}</span>
            <span aria-hidden>·</span>
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${chat.tone === "danger" ? "bg-[#ff6b5e]" : chat.tone === "ok" ? "bg-[#3ddc97]" : chat.tone === "active" ? "bg-[#38d6f5]" : "bg-white/50"}`} aria-hidden />
            <span className="truncate">{chat.statusLabel}</span>
          </p>
        </div>
        <button type="button" onClick={onSayHi} disabled={!canGreet || waving} title={canGreet ? "Wave hello again" : "Resume the simulation to wave"}
          className="h-7 rounded-full border border-white/25 px-2.5 text-[11px] text-white/90 transition-colors hover:bg-white/10 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]">
          Say hi
        </button>
        <button type="button" onClick={close} aria-label={`Close chat with ${chat.name}`}
          className="inline-flex h-7 w-7 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </header>
      <p className="hidden truncate border-b border-line bg-sunken/60 px-3 py-1.5 text-[11px] text-muted md:block" title={chat.detail}>Now: {chat.detail || chat.statusLabel}</p>
      <TaskStrip tasks={chat.tasks} />

      <ol ref={listRef} role="log" aria-label={`Conversation with ${chat.name}`} aria-live="polite" className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {visible.map((m) => <Message key={m.id} m={m} busy={busy} onAnswer={onAnswer} />)}
        {typing && <Typing name={chat.name} waving={waving} />}
      </ol>

      <div className="border-t border-line px-3 pb-2 pt-2 md:pb-3">
        <div role="group" aria-label="Suggested tasks" className="mb-2 flex gap-1.5 overflow-x-auto md:flex-wrap md:overflow-visible">
          {QUICK_TASKS[chat.agent].map((q) => (
            <button key={q.id} type="button" disabled={cooldown} onClick={() => quick(q.id)} title={`Assign “${q.title}” (demo)`}
              className="h-7 shrink-0 rounded-full border border-[#38d6f5]/60 bg-[#38d6f5]/10 px-2.5 text-[11px] font-medium text-fg transition-colors hover:bg-[#38d6f5]/25 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#38d6f5]">
              {q.label}
            </button>
          ))}
        </div>
        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) send(); }}>
          <label className="sr-only" htmlFor="office-chat-input">Message {chat.name}</label>
          <textarea
            id="office-chat-input" ref={inputRef} rows={1} value={draft} maxLength={MAX_MESSAGE_LENGTH}
            onChange={(e) => { setDraft(e.target.value); if (error) setError(null); }} onKeyDown={onKey}
            placeholder={`Ask ${chat.name} for a task…`} aria-describedby="office-chat-hint" aria-invalid={!!error}
            className="max-h-24 min-h-9 flex-1 resize-none rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] leading-snug text-fg outline-none placeholder:text-faint focus:border-[#38d6f5] focus:ring-2 focus:ring-[#38d6f5]/30"
            style={{ fieldSizing: "content" } as CSSProperties}
          />
          <button type="submit" disabled={!draft.trim()} aria-label="Send message"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white transition-colors disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#38d6f5]"
            style={{ background: NAVY }}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M5 12h13M13 6l6 6-6 6" /></svg>
          </button>
        </form>
        <p id="office-chat-hint" className={`mt-1.5 justify-between gap-2 text-[10px] ${error ? "flex text-danger" : "hidden text-faint md:flex"}`}>
          <span>{error ?? "Demo chat · simulated replies, no AI model · Enter to send"}</span>
          {draft.length > MAX_MESSAGE_LENGTH - 60 && <span className="tabular-nums">{draft.length}/{MAX_MESSAGE_LENGTH}</span>}
        </p>
      </div>
    </section>
  );
}
