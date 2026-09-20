import { useEffect, useRef, useState } from "react";
import { applyMention, mentionQuery } from "../lib/mentions";
import type { AttachmentIn } from "../api/client";
import { Button, Kbd } from "./ui";
import { CloseIcon } from "./icons";

// Paste constraints for attached images (client-side guard; the API re-validates).
const MAX_IMAGES = 4;
const MAX_DIM = 1568; // downscale huge screenshots so data URLs stay manageable
const MIN_DIM = 64;
const MAX_CHARS = 4_500_000;

/** Decodes an image File into a (optionally downscaled) PNG data URL. */
async function toDataUrl(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, MAX_DIM / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(MIN_DIM, Math.round(bitmap.width * scale));
    const h = Math.max(MIN_DIM, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas unavailable");
    ctx.drawImage(bitmap, 0, 0, w, h);
    return canvas.toDataURL("image/png");
  } finally {
    bitmap.close();
  }
}

/** Reads pasted/dropped image files into attachments (data URL + file name). Returns the decoded ones and whether any file was skipped. */
async function decodeImages(files: File[]): Promise<{ attachments: AttachmentIn[]; skipped: boolean }> {
  const attachments: AttachmentIn[] = [];
  let skipped = false;
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    try {
      const url = await toDataUrl(f);
      if (url.length > MAX_CHARS) {
        skipped = true;
        continue;
      }
      attachments.push({ url, name: f.name || undefined });
    } catch {
      skipped = true; // undecodable image: skip it
    }
  }
  return { attachments, skipped };
}

/**
 * The prompt. A `❯` in the gutter, the text you type, and the keys that send it — the one place
 * the interface is allowed to look like a terminal on purpose.
 */
export default function Composer({ handles, onSend, disabled, hint, autoFocus }: { handles: string[]; onSend: (text: string, attachments: AttachmentIn[]) => Promise<void>; disabled?: boolean; hint?: string; autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [sel, setSel] = useState(0);
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentIn[]>([]);
  const [skipped, setSkipped] = useState(false);
  const [dropped, setDropped] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  // Auto-focus the textarea on mount when requested (e.g. new thread).
  useEffect(() => { if (autoFocus && ref.current) ref.current.focus(); }, [autoFocus]);
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
  const attach = (files: File[]) => {
    void decodeImages(files).then(({ attachments: atts, skipped: bad }) => {
      setAttachments((imgs) => [...imgs, ...atts].slice(0, MAX_IMAGES));
      if (attachments.length + atts.length > MAX_IMAGES) setDropped(true);
      setSkipped(bad);
    });
  };
  // Clear only once the send succeeds: a failed post keeps the draft and its images to
  // retry, and the rejection stops here rather than escaping as an unhandled promise.
  const send = async () => {
    const t = text.trim();
    if ((!t && attachments.length === 0) || sending) return;
    setSending(true);
    try {
      await onSend(t, attachments);
      setText("");
      setCaret(0);
      setSel(0);
      setAttachments([]);
      setSkipped(false);
      setDropped(false);
    } catch {
      /* the caller renders the error; keep the draft */
    } finally {
      setSending(false);
    }
  };
  const canSend = !disabled && !sending && (!!text.trim() || attachments.length > 0);
  return (
    <div className="relative">
      {options.length > 0 && (
        <div role="listbox" aria-label="Mention a bot" className="absolute bottom-full left-6 z-10 mb-1 w-60 overflow-hidden rounded-ui border border-line bg-surface py-1 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.45)]">
          {options.map((h, i) => (
            <div key={h} role="option" aria-selected={i === sel} onMouseDown={(e) => { e.preventDefault(); pick(h); }}
              className={`cursor-pointer px-3 py-1.5 text-[13px] ${i === sel ? "bg-sunken text-fg" : "text-muted"}`}>
              <span className="text-accent-strong">@</span>{h}
            </div>
          ))}
        </div>
      )}
      <div className={`flex flex-col rounded-ui border bg-surface transition-colors ${disabled ? "border-line opacity-70" : "border-line focus-within:border-accent"}`}>
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachments.map((a, i) => (
              <div key={`${i}:${a.url.slice(-24)}`} className="relative">
                <img src={a.url} alt={a.name ?? `attached image ${i + 1}`} title={a.name} className="h-16 rounded-ui border border-line" />
                <button
                  type="button"
                  aria-label={`Remove attached image ${i + 1}`}
                  className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface text-fg hover:bg-sunken"
                  onClick={() => setAttachments((imgs) => imgs.filter((_, j) => j !== i))}
                ><CloseIcon className="h-3 w-3" /></button>
              </div>
            ))}
          </div>
        )}
        {(skipped || dropped) && (
          <p className="px-3 pt-2 text-xs text-warn">
            {[
              skipped ? "Some pasted images could not be read and were skipped." : null,
              dropped ? `Only the first ${MAX_IMAGES} attached images are kept per message.` : null,
            ].filter(Boolean).join(" ")}
          </p>
        )}
        <div className="flex items-start gap-2 px-3 pt-2.5">
          <span className="mt-[5px] select-none text-[13px] font-semibold leading-none text-accent" aria-hidden>❯</span>
          <textarea
            ref={ref}
            rows={3}
            value={text}
            disabled={disabled}
            aria-label="Message"
            placeholder={hint ?? "Type a message. @handle addresses a bot."}
            className="min-h-[4.25rem] flex-1 resize-none bg-transparent text-[13.5px] leading-relaxed text-fg outline-none placeholder:text-faint disabled:cursor-not-allowed"
            onChange={(e) => { setText(e.target.value); setCaret(e.target.selectionStart); setSel(0); }}
            onSelect={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData?.items ?? [], (it) => (it.kind === "file" ? it.getAsFile() : null))
                .filter((f): f is File => !!f);
              if (!files.length) return; // plain-text paste falls through unchanged
              e.preventDefault();
              attach(files);
            }}
            onKeyDown={(e) => {
              if (options.length) {
                if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => (s + 1) % options.length); return; }
                if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => (s - 1 + options.length) % options.length); return; }
                if (e.key === "Tab" || e.key === "Enter") { e.preventDefault(); pick(options[sel]); return; }
              }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
          />
        </div>
        <div className="flex items-center justify-between gap-3 px-3 pb-2 pt-1">
          <div className="hidden items-center gap-3 text-[11px] text-faint sm:flex" aria-hidden>
            <span className="inline-flex items-center gap-1"><Kbd>⏎</Kbd> send</span>
            <span className="inline-flex items-center gap-1"><Kbd>⇧⏎</Kbd> new line</span>
            <span className="inline-flex items-center gap-1"><Kbd>@</Kbd> mention a bot</span>
            <span className="inline-flex items-center gap-1"><Kbd>⌘V</Kbd> paste an image</span>
          </div>
          <Button size="sm" onClick={() => void send()} disabled={!canSend} className="ml-auto">
            {sending ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}
