import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Api } from "../api/client";
import { Button, Dialog, ErrorText, Spinner } from "./ui";
import { FolderIcon } from "./icons";

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
  const rootTab = (target: string, label: string) => {
    const selected = (target === "~") === inHome;
    return (
      <button type="button" role="tab" aria-selected={selected} onClick={() => setPath(target)}
        className={`h-7 rounded-[2px] px-3 text-xs transition-colors ${selected ? "bg-sunken font-medium text-fg" : "text-muted hover:text-fg"}`}>{label}</button>
    );
  };
  return (
    <Dialog title="Choose working directory" titleId="directory-picker-title" onClose={onClose} className="gap-3">
      <div role="tablist" className="inline-flex self-start rounded-ui border border-line p-0.5">{rootTab(".", "Workspace")}{rootTab("~", "Home")}</div>
      <div className="flex items-center gap-2 text-sm">
        <Button variant="secondary" size="sm" className="shrink-0" disabled={!listing.data?.parent} onClick={() => listing.data?.parent && setPath(listing.data.parent)} title="Up one level">↑ Up</Button>
        <code className="min-w-0 flex-1 truncate rounded-ui border border-line bg-sunken px-2 py-1 text-xs" data-testid="picker-path">{path === "." ? ". (workspace root)" : path}</code>
      </div>
      <div className="scrollbar-subtle max-h-72 overflow-y-auto rounded-ui border border-line">
        {listing.isLoading && <div className="p-3"><Spinner /></div>}
        {listing.error && <div className="p-3"><ErrorText error={listing.error} /></div>}
        {listing.data && listing.data.entries.length === 0 && <p className="p-3 text-xs text-muted">No subfolders.</p>}
        {listing.data?.entries.map((entry) => (
          <button key={entry.path} type="button" onClick={() => setPath(entry.path)}
            className="flex w-full items-center gap-2 border-b border-line px-3 py-1.5 text-left text-[13px] last:border-b-0 hover:bg-sunken">
            <FolderIcon className="h-4 w-4 shrink-0 text-faint" />
            <span className="truncate">{entry.name}</span>
          </button>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => onSelect(path)} disabled={!listing.data}>Use this folder</Button>
      </div>
    </Dialog>
  );
}
