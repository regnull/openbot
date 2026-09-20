import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Api } from "../api/client";
import Avatar from "../components/Avatar";
import { Button, Card, EmptyState, ErrorText, Field, Input, PageTitle, SectionTitle, Select, Spinner } from "../components/ui";
import { FolderIcon } from "../components/icons";
import { parseTs } from "../lib/time";
import { initialPickerPath, normalizeWorkingDirectory } from "../lib/workingDirectory";
import DirectoryPicker from "../components/DirectoryPicker";

export default function ThreadsPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const threads = useQuery({ queryKey: ["threads"], queryFn: Api.listThreads });
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  const [title, setTitle] = useState("");
  const [handles, setHandles] = useState<string[]>([]);
  const [defaultBot, setDefaultBot] = useState("chief_of_staff");
  const [workingDirectory, setWorkingDirectory] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const enabledBots = (bots.data ?? []).filter((b) => b.enabled);
  const effectiveDefaultBot = enabledBots.some((b) => b.handle === defaultBot) ? defaultBot : enabledBots[0]?.handle;
  const workingDirectoryValidation = normalizeWorkingDirectory(workingDirectory);
  const botIconByHandle = useMemo(() => new Map((bots.data ?? []).map((b) => [b.handle, b.icon])), [bots.data]);
  const create = useMutation({
    mutationFn: () => {
      if (!workingDirectoryValidation.ok) throw new Error(workingDirectoryValidation.error ?? "Invalid working directory");
      return Api.createThread({
        title,
        handles,
        ...(effectiveDefaultBot ? { default_bot_handle: effectiveDefaultBot } : {}),
        ...(workingDirectoryValidation.value ? { working_directory: workingDirectoryValidation.value } : {}),
      });
    },
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["threads"] }); nav(`/threads/${t.id}`); },
  });
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageTitle>Threads</PageTitle>
      <Card className="space-y-4">
        <SectionTitle>New thread</SectionTitle>
        <Field label="Title" hint="Optional. Without one, the thread is named after who is in it.">
          <Input placeholder="What is this thread about?" value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Working directory" hint="Where the thread's file and shell tools run. Leave blank for the workspace root, or use a path under it or under your home, such as ~/work/project.">
          <div className="flex gap-2">
            <Input placeholder=". (workspace root)" value={workingDirectory} onChange={(e) => setWorkingDirectory(e.target.value)} />
            <Button variant="secondary" onClick={() => setPickerOpen(true)} title="Browse for directory" aria-label="Browse for directory" className="w-9 px-0">
              <FolderIcon className="h-4 w-4" />
            </Button>
          </div>
        </Field>
        {workingDirectoryValidation.error && <p className="text-xs text-danger">{workingDirectoryValidation.error}</p>}
        {pickerOpen && (
          <DirectoryPicker initialPath={initialPickerPath(workingDirectory)} onClose={() => setPickerOpen(false)}
            onSelect={(path) => { setWorkingDirectory(path === "." ? "" : path); setPickerOpen(false); }} />
        )}
        <div className="space-y-1.5">
          <span className="block text-xs font-medium text-muted">Bots in this thread</span>
          <div className="flex flex-wrap gap-1.5">
            {enabledBots.map((b) => {
              const on = handles.includes(b.handle);
              return (
                <label key={b.id} className={`cursor-pointer select-none rounded-ui border px-2 py-1 text-xs transition-colors ${on ? "border-accent bg-accent/10 text-accent-strong" : "border-line text-muted hover:border-line-strong hover:text-fg"}`}>
                  <input type="checkbox" className="sr-only" checked={on} onChange={() => setHandles((h) => (h.includes(b.handle) ? h.filter((x) => x !== b.handle) : [...h, b.handle]))} />@{b.handle}
                </label>
              );
            })}
            {bots.data?.length === 0 && <p className="font-sans text-[13px] text-muted">No bots yet. <Link className="underline hover:text-fg" to="/bots/new">Create one</Link> to have someone to talk to.</p>}
          </div>
          {enabledBots.length > 0 && <span className="block font-sans text-xs text-faint">Any bot can still be mentioned later with @handle.</span>}
        </div>
        {enabledBots.length > 0 && (
          <Field label="Default bot" hint="Answers messages that mention nobody.">
            <Select value={effectiveDefaultBot ?? ""} onChange={(e) => setDefaultBot(e.target.value)}>
              {enabledBots.map((b) => <option key={b.id} value={b.handle}>@{b.handle}</option>)}
            </Select>
          </Field>
        )}
        <ErrorText error={create.error} />
        <Button onClick={() => create.mutate()} disabled={create.isPending || !workingDirectoryValidation.ok}>Start thread</Button>
      </Card>
      <section className="space-y-3">
        <SectionTitle>All threads</SectionTitle>
        <ErrorText error={threads.error} />
        {threads.isLoading && <Spinner />}
        {threads.data && threads.data.length > 0 && (
          <ul className="divide-y divide-line overflow-hidden rounded-ui border border-line bg-surface">
            {threads.data.map((t) => (
              <li key={t.id}>
                <Link to={`/threads/${t.id}`} className="flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-sunken/60">
                  <div className="flex shrink-0 -space-x-1.5">{t.participants.map((p) => <Avatar key={p.actor_id} name={p.name} kind={p.kind} small icon={p.kind === "bot" ? botIconByHandle.get(p.handle) : undefined} />)}</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium">{t.title || t.participants.map((p) => p.handle).join(", ")}</div>
                    <div className="flex flex-wrap gap-x-3 text-[11px] leading-4 text-muted">
                      <span className="truncate">{t.participants.map((p) => `@${p.handle}`).join(" ")}</span>
                      <span><span className="text-faint">default </span>@{t.default_bot_handle ?? "chief_of_staff"}</span>
                      <span className="truncate"><span className="text-faint">cwd </span>{t.working_directory ?? "."}</span>
                    </div>
                  </div>
                  <time className="shrink-0 text-[11px] text-faint" dateTime={t.last_message_at ?? undefined}>{t.last_message_at ? parseTs(t.last_message_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "no messages"}</time>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {threads.data?.length === 0 && <EmptyState>No threads yet. Start one above and a bot will pick it up.</EmptyState>}
      </section>
    </div>
  );
}
