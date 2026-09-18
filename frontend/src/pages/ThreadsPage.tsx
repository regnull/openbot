import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Api } from "../api/client";
import Avatar from "../components/Avatar";
import { Button, Card, ErrorText, Input, Spinner } from "../components/ui";
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
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Threads</h1>
      <Card className="space-y-3">
        <h2 className="font-medium">New thread</h2>
        <Input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <label className="block space-y-1 text-sm">
          <span className="text-zinc-600 dark:text-zinc-400">Working directory for thread tools</span>
          <div className="flex gap-2">
            <Input placeholder=". (workspace root)" value={workingDirectory} onChange={(e) => setWorkingDirectory(e.target.value)} />
            <Button variant="secondary" onClick={() => setPickerOpen(true)} title="Browse for directory" className="shrink-0">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
            </Button>
          </div>
          <span className="block text-xs text-zinc-500">Leave blank to use the current workspace root. Enter a directory under the workspace, or a home-relative path such as ~/work/project.</span>
        </label>
        {workingDirectoryValidation.error && <p className="text-xs text-red-600">{workingDirectoryValidation.error}</p>}
        {pickerOpen && (
          <DirectoryPicker initialPath={initialPickerPath(workingDirectory)} onClose={() => setPickerOpen(false)}
            onSelect={(path) => { setWorkingDirectory(path === "." ? "" : path); setPickerOpen(false); }} />
        )}
        <div className="flex flex-wrap gap-2">
          {enabledBots.map((b) => (
            <label key={b.id} className={`cursor-pointer rounded-full border px-3 py-1 text-sm ${handles.includes(b.handle) ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-zinc-300 dark:border-zinc-700"}`}>
              <input type="checkbox" className="hidden" checked={handles.includes(b.handle)} onChange={() => setHandles((h) => (h.includes(b.handle) ? h.filter((x) => x !== b.handle) : [...h, b.handle]))} />@{b.handle}
            </label>
          ))}
          {bots.data?.length === 0 && <p className="text-sm text-zinc-500">No bots yet — <Link className="underline" to="/bots/new">create one</Link> to have someone to talk to.</p>}
        </div>
        {enabledBots.length > 0 && (
          <label className="block space-y-1 text-sm">
            <span className="text-zinc-600 dark:text-zinc-400">Default bot for unmentioned messages</span>
            <select className="w-full rounded border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950" value={effectiveDefaultBot ?? ""} onChange={(e) => setDefaultBot(e.target.value)}>
              {enabledBots.map((b) => <option key={b.id} value={b.handle}>@{b.handle}</option>)}
            </select>
          </label>
        )}
        <ErrorText error={create.error} />
        <Button onClick={() => create.mutate()} disabled={create.isPending || !workingDirectoryValidation.ok}>Start thread</Button>
      </Card>
      <ErrorText error={threads.error} />
      {threads.isLoading && <Spinner />}
      <div className="space-y-2">
        {threads.data?.map((t) => (
          <Link key={t.id} to={`/threads/${t.id}`} className="block">
            <Card className="flex items-center gap-3 hover:border-blue-400">
              <div className="flex -space-x-2">{t.participants.map((p) => <Avatar key={p.actor_id} name={p.name} kind={p.kind} small icon={p.kind === "bot" ? botIconByHandle.get(p.handle) : undefined} />)}</div>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{t.title || t.participants.map((p) => p.handle).join(", ")}</div>
                <div className="text-xs text-zinc-500">{t.participants.map((p) => `@${p.handle}`).join(" ")} · default @{t.default_bot_handle ?? "chief_of_staff"} · cwd {t.working_directory ?? "."}</div>
              </div>
              <div className="shrink-0 text-xs text-zinc-500">{t.last_message_at ? parseTs(t.last_message_at).toLocaleString() : "no messages"}</div>
            </Card>
          </Link>
        ))}
        {threads.data?.length === 0 && <p className="text-sm text-zinc-500">No threads yet.</p>}
      </div>
    </div>
  );
}