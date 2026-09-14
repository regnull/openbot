import { useRef, useState } from "react";
import { applyMention, mentionQuery } from "../lib/mentions";
import { Button } from "./ui";

export default function Composer({ handles, onSend, disabled, hint }: { handles: string[]; onSend: (text: string) => Promise<void>; disabled?: boolean; hint?: string }) {
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [sel, setSel] = useState(0);
  const [sending, setSending] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const q = mentionQuery(text, caret);
  const options = q ? handles.filter((h) => h.startsWith(q.query)).slice(0, 6) : [];
  const pick = (h: string) => {
    if (!q) return;
    const r = applyMention(text, q.start, caret, h);
    setText(r.text);
    setCaret(r.caret);
    setSel(0);
    requestAnimationFrame(() => { ref.current?.focus(); ref.current?.setSelectionRange(r.caret, r.caret); });
  };
  // Clear only once the send succeeds: a failed post keeps the draft to retry, and the
  // rejection stops here rather than escaping as an unhandled promise.
  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    try {
      await onSend(t);
      setText("");
      setCaret(0);
      setSel(0);
    } catch {
      /* the caller renders the error; keep the draft */
    } finally {
      setSending(false);
    }
  };
  return (
    <div className="relative">
      {options.length > 0 && (
        <div className="absolute bottom-full mb-1 w-64 rounded-md border border-zinc-200 bg-white shadow dark:border-zinc-700 dark:bg-zinc-900">
          {options.map((h, i) => (
            <div key={h} onMouseDown={(e) => { e.preventDefault(); pick(h); }} className={`cursor-pointer px-3 py-1 text-sm ${i === sel ? "bg-zinc-100 dark:bg-zinc-800" : ""}`}>@{h}</div>
          ))}
        </div>
      )}
      <textarea
        ref={ref}
        rows={3}
        value={text}
        disabled={disabled}
        placeholder={hint ?? "Message… use @handle to address a bot"}
        className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950"
        onChange={(e) => { setText(e.target.value); setCaret(e.target.selectionStart); setSel(0); }}
        onSelect={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart)}
        onKeyDown={(e) => {
          if (options.length) {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => (s + 1) % options.length); return; }
            if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => (s - 1 + options.length) % options.length); return; }
            if (e.key === "Tab" || e.key === "Enter") { e.preventDefault(); pick(options[sel]); return; }
          }
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
        }}
      />
      <div className="mt-1 flex justify-end"><Button onClick={() => void send()} disabled={disabled || sending || !text.trim()}>{sending ? "Sending…" : "Send"}</Button></div>
    </div>
  );
}
