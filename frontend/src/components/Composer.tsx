import { useRef, useState } from "react";
import { applyMention, mentionQuery } from "../lib/mentions";
import type { AttachmentIn } from "../api/client";
import { Button } from "./ui";

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

export default function Composer({ handles, onSend, disabled, hint }: { handles: string[]; onSend: (text: string, attachments: AttachmentIn[]) => Promise<void>; disabled?: boolean; hint?: string }) {
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [sel, setSel] = useState(0);
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentIn[]>([]);
  const [skipped, setSkipped] = useState(false);
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
  const attach = (files: File[]) => {
    void decodeImages(files).then(({ attachments: atts, skipped: bad }) => {
      setAttachments((imgs) => [...imgs, ...atts].slice(0, MAX_IMAGES));
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
      {attachments.length > 0 && (
        <div className="mb-1 flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <div key={`${i}:${a.url.slice(-24)}`} className="relative">
              <img src={a.url} alt={a.name ?? `attached image ${i + 1}`} title={a.name} className="h-16 rounded border border-zinc-200 dark:border-zinc-700" />
              <button
                type="button"
                aria-label={`Remove attached image ${i + 1}`}
                className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-xs leading-none text-white hover:bg-zinc-600"
                onClick={() => setAttachments((imgs) => imgs.filter((_, j) => j !== i))}
              >×</button>
            </div>
          ))}
        </div>
      )}
      {skipped && <p className="mb-1 text-xs text-amber-600">Some pasted images could not be read and were skipped.</p>}
      <textarea
        ref={ref}
        rows={3}
        value={text}
        disabled={disabled}
        placeholder={hint ?? "Message… use @handle to address a bot"}
        className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:border-zinc-700 dark:bg-zinc-950"
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
      <div className="mt-1 flex justify-end">
        <Button onClick={() => void send()} disabled={disabled || sending || (!text.trim() && attachments.length === 0)}>
          {sending ? "Sending…" : "Send"}
        </Button>
      </div>
    </div>
  );
}
