import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Api } from "../api/client";
import { Button, ErrorText, Spinner } from "./ui";

/**
 * Server-backed folder chooser for a thread's working directory.
 *
 * A browser's native directory dialog never reveals the chosen folder's full path, only its
 * name, so it cannot express "~/work/core-web". The backend runs on the user's machine and
 * already knows the rules (inside the workspace root or the home directory), so we walk the
 * filesystem through it instead.
 */
export default function DirectoryPicker({ initialPath, onSelect, onClose }: { initialPath: string; onSelect: (path: string) => void; onClose: () => void }) {
  const [path, setPath] = useState(initialPath);
  const listing = useQuery({ queryKey: ["workspace-directories", path], queryFn: () => Api.listDirectories(path), retry: false });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const inHome = path === "~" || path.startsWith("~/");
  const rootTab = (target: string, label: string) => (
    <button type="button" onClick={() => setPath(target)}
      className={`rounded-md px-3 py-1 text-sm ${(target === "~") === inHome ? "bg-blue-600 text-white" : "border border-zinc-300 dark:border-zinc-700"}`}>{label}</button>
  );
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="directory-picker-title">
      <div className="flex w-full max-w-lg flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-zinc-800 dark:bg-zinc-900" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <h2 id="directory-picker-title" className="text-lg font-semibold">Choose working directory</h2>
          <button type="button" aria-label="Close" className="text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200" onClick={onClose}>✕</button>
        </div>
        <div className="flex gap-1">{rootTab(".", "Workspace")}{rootTab("~", "Home")}</div>
        <div className="flex items-center gap-2 text-sm">
          <Button variant="secondary" className="shrink-0" disabled={!listing.data?.parent} onClick={() => listing.data?.parent && setPath(listing.data.parent)} title="Up one level">↑ Up</Button>
          <code className="min-w-0 flex-1 truncate rounded bg-zinc-100 px-2 py-1 dark:bg-zinc-800" data-testid="picker-path">{path === "." ? ". (workspace root)" : path}</code>
        </div>
        <div className="scrollbar-subtle max-h-72 overflow-y-auto rounded-md border border-zinc-200 dark:border-zinc-800">
          {listing.isLoading && <div className="p-3"><Spinner /></div>}
          {listing.error && <div className="p-3"><ErrorText error={listing.error} /></div>}
          {listing.data && listing.data.entries.length === 0 && <p className="p-3 text-sm text-zinc-500">No subfolders.</p>}
          {listing.data?.entries.map((entry) => (
            <button key={entry.path} type="button" onClick={() => setPath(entry.path)}
              className="flex w-full items-center gap-2 border-b border-zinc-100 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-800">
              <svg className="h-4 w-4 shrink-0 text-zinc-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <span className="truncate">{entry.name}</span>
            </button>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onSelect(path)} disabled={!listing.data}>Use this folder</Button>
        </div>
      </div>
    </div>
  );
}
