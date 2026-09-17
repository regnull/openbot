import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Api, getApiKey, setApiKey } from "../api/client";
import type { AppSetting, McpServer } from "../api/types";
import { Badge, Button, Card, ErrorText, Field, Input } from "../components/ui";
import { formatSettingValue, groupSettings, parseSettingInput, type SettingGroup } from "../lib/appSettings";
import { mcpActions, mcpInFlight, mcpStatusBadge, validateNewMcpServer } from "../lib/mcpServers";

const emptyExt = { handle: "", name: "", webhook_url: "", webhook_secret: "" };

export default function SettingsPage() {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: Api.getProviders });
  const tools = useQuery({ queryKey: ["tools"], queryFn: Api.listTools });
  const actors = useQuery({ queryKey: ["actors"], queryFn: Api.listActors });
  const [key, setKey] = useState(getApiKey());
  const [ext, setExt] = useState(emptyExt);
  const createExt = useMutation({
    mutationFn: () => Api.createActor({ handle: ext.handle, name: ext.name, webhook_url: ext.webhook_url || null, webhook_secret: ext.webhook_secret || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["actors"] }); setExt(emptyExt); },
  });
  const delExt = useMutation({ mutationFn: (id: string) => Api.deleteActor(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["actors"] }) });
  const externals = actors.data?.filter((a) => a.kind === "external") ?? [];
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <RuntimeSettings />

      <McpServersCard />

      <Card className="space-y-2">
        <h2 className="font-medium">Providers</h2>
        <ErrorText error={providers.error} />
        <div className="flex flex-wrap gap-2">
          {providers.data?.providers.map((p) => <Badge key={p.id} tone={p.configured ? "green" : "zinc"}>{p.id}: {p.configured ? "configured" : "no key"}</Badge>)}
        </div>
        <p className="text-sm text-zinc-500">Embeddings: {providers.data?.embedding_model} · {providers.data?.embeddings_configured ? "configured" : "not configured (memory search is not semantic)"}</p>
        <p className="text-xs text-zinc-500">Keys are read from the server environment (.env). Restart the server after changing them.</p>
      </Card>

      <Card className="space-y-2">
        <h2 className="font-medium">External actors</h2>
        <p className="text-sm text-zinc-500">External systems post as themselves via the API and receive their inbox by signed webhook.</p>
        <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
          {externals.map((a) => (
            <li key={a.id} className="flex items-center gap-2 py-2">
              <span className="font-mono">@{a.handle}</span>
              <span className="text-zinc-500">{a.name}</span>
              <span className="truncate text-xs text-zinc-500">{a.webhook_url ?? "polling only"}</span>
              <Button variant="secondary" className="ml-auto shrink-0" onClick={() => delExt.mutate(a.id)} disabled={delExt.isPending}>Delete</Button>
            </li>
          ))}
          {externals.length === 0 && <li className="py-2 text-zinc-500">None yet.</li>}
        </ul>
        <ErrorText error={delExt.error} />
        <form className="grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); createExt.mutate(); }}>
          <Field label="Handle"><Input value={ext.handle} onChange={(e) => setExt({ ...ext, handle: e.target.value })} pattern="[a-z0-9_\-]{2,32}" required /></Field>
          <Field label="Name"><Input value={ext.name} onChange={(e) => setExt({ ...ext, name: e.target.value })} required /></Field>
          <Field label="Webhook URL (optional)"><Input value={ext.webhook_url} onChange={(e) => setExt({ ...ext, webhook_url: e.target.value })} /></Field>
          <Field label="Webhook secret (optional)"><Input value={ext.webhook_secret} onChange={(e) => setExt({ ...ext, webhook_secret: e.target.value })} /></Field>
          <div className="sm:col-span-2"><ErrorText error={createExt.error} /><Button type="submit" disabled={createExt.isPending}>Add external actor</Button></div>
        </form>
      </Card>

      <Card className="space-y-2">
        <h2 className="font-medium">Tools</h2>
        <ErrorText error={tools.error} />
        {tools.data?.errors.map((e) => <p key={e.file} className="text-xs text-red-600">{e.file}: {e.error}</p>)}
        <ul className="text-sm">
          {tools.data?.tools.map((t) => (
            <li key={t.name}><span className="font-mono">{t.name}</span> <span className="text-zinc-500">— {t.description}</span> <span className="text-xs text-zinc-400">({t.source})</span></li>
          ))}
        </ul>
      </Card>

      <Card className="space-y-2">
        <h2 className="font-medium">API key</h2>
        <p className="text-sm text-zinc-500">Only needed when the server sets OPENBOT_API_KEY. Stored in this browser.</p>
        <div className="flex gap-2">
          <Input value={key} onChange={(e) => setKey(e.target.value)} placeholder="X-API-Key" />
          <Button className="shrink-0" onClick={() => { setApiKey(key.trim()); location.reload(); }}>Save</Button>
        </div>
      </Card>
    </div>
  );
}


function RuntimeSettings() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: Api.getSettings });
  if (settings.isLoading) return null;
  if (!settings.data) return <ErrorText error={settings.error} />;
  return (
    <>
      {groupSettings(settings.data).map((g) => <SettingsGroupCard key={g.name} group={g} />)}
    </>
  );
}

function SettingsGroupCard({ group }: { group: SettingGroup }) {
  const qc = useQueryClient();
  // Local edits keyed by setting; a key is present only while it differs from what the server has.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const refresh = (rows: AppSetting[]) => { qc.setQueryData(["settings"], rows); setDrafts({}); setErrors({}); };
  const save = useMutation({ mutationFn: (updates: Record<string, unknown>) => Api.patchSettings(updates), onSuccess: refresh });
  const reset = useMutation({ mutationFn: (key: string) => Api.resetSetting(key), onSuccess: refresh });
  const dirty = Object.keys(drafts).length > 0;
  const submit = () => {
    const updates: Record<string, unknown> = {};
    const errs: Record<string, string> = {};
    for (const item of group.items) {
      if (!(item.key in drafts)) continue;
      const parsed = parseSettingInput(item.type, drafts[item.key]);
      if ("error" in parsed) errs[item.key] = parsed.error; else updates[item.key] = parsed.value;
    }
    setErrors(errs);
    if (Object.keys(errs).length === 0 && Object.keys(updates).length > 0) save.mutate(updates);
  };
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{group.name}</h2>
        <span className="text-xs text-zinc-500">Takes effect on the next run. Environment values are the defaults.</span>
      </div>
      <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
        {group.items.map((item) => {
          const current = formatSettingValue(item.type, item.value);
          const draft = item.key in drafts ? drafts[item.key] : current;
          const setDraft = (v: string) => setDrafts((d) => { const n = { ...d }; if (v === current) delete n[item.key]; else n[item.key] = v; return n; });
          return (
            <div key={item.key} className="grid gap-2 py-3 sm:grid-cols-[1fr_14rem]">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{item.label}</span>
                  {item.overridden && <Badge tone="amber">overridden</Badge>}
                  {item.overridden && (
                    <button type="button" className="text-xs text-zinc-500 underline" disabled={reset.isPending} onClick={() => reset.mutate(item.key)}>
                      reset to {formatSettingValue(item.type, item.default) || "empty"}
                    </button>
                  )}
                </div>
                <div className="text-xs text-zinc-500">{item.description}</div>
                {errors[item.key] && <div className="text-xs text-red-600">{errors[item.key]}</div>}
              </div>
              <div className="flex items-center">
                {item.type === "bool" ? (
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={draft === "true"} onChange={(e) => setDraft(String(e.target.checked))} /> {draft === "true" ? "on" : "off"}
                  </label>
                ) : (
                  <Input value={draft} inputMode={item.type === "int" || item.type === "float" ? "decimal" : undefined}
                    className={item.key in drafts ? "border-amber-400" : ""} onChange={(e) => setDraft(e.target.value)}
                    placeholder={item.type === "list" ? "comma-separated" : ""} />
                )}
              </div>
            </div>
          );
        })}
      </div>
      <ErrorText error={save.error ?? reset.error} />
      <div className="flex gap-2">
        <Button onClick={submit} disabled={!dirty || save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
        {dirty && <Button variant="secondary" onClick={() => { setDrafts({}); setErrors({}); }}>Discard</Button>}
      </div>
    </Card>
  );
}

function McpServersCard() {
  const qc = useQueryClient();
  const servers = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: Api.listMcpServers,
    refetchInterval: (q) => (mcpInFlight(q.state.data ?? []) ? 2000 : false),
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["mcp-servers"] }); qc.invalidateQueries({ queryKey: ["tools"] }); };
  const connect = useMutation({
    mutationFn: (name: string) => Api.connectMcpServer(name),
    onSuccess: (r) => { if (r.authorization_url) window.open(r.authorization_url, "_blank", "noopener"); refresh(); },
  });
  const disconnect = useMutation({ mutationFn: (name: string) => Api.disconnectMcpServer(name), onSuccess: refresh });
  const forget = useMutation({ mutationFn: (name: string) => Api.forgetMcpCredentials(name), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (name: string) => Api.removeMcpServer(name), onSuccess: refresh });
  const busy = connect.isPending || disconnect.isPending || forget.isPending || remove.isPending;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [adding, setAdding] = useState(false);
  // A server that starts authorizing on its own (just added, or Connect from another tab) publishes its
  // authorization URL on the listing; open each one once.
  const opened = useRef(new Set<string>());
  useEffect(() => {
    for (const s of servers.data ?? []) {
      if (s.authorization_url && !opened.current.has(s.authorization_url)) {
        opened.current.add(s.authorization_url);
        window.open(s.authorization_url, "_blank", "noopener");
      }
    }
  }, [servers.data]);
  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">MCP servers</h2>
        <Button variant="secondary" onClick={() => setAdding(true)}>Add server</Button>
      </div>
      <p className="text-sm text-zinc-500">Tools from Model Context Protocol servers. Add a remote server here, or configure any server (including local stdio ones) in <code>mcp.json</code>, see <code>mcp.example.json</code>. Tools appear in the tool list as <code>server__tool</code> and are picked per bot like any other tool.</p>
      {adding && <AddMcpServerDialog onClose={() => setAdding(false)} onAdded={() => { setAdding(false); refresh(); }} />}
      <ErrorText error={servers.error ?? connect.error ?? disconnect.error ?? forget.error ?? remove.error} />
      {servers.data?.length === 0 && <p className="text-sm text-zinc-500">No servers configured.</p>}
      <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
        {servers.data?.map((s: McpServer) => {
          const badge = mcpStatusBadge(s);
          const actions = mcpActions(s);
          return (
            <li key={s.name} className="space-y-1 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{s.name}</span>
                <Badge tone={badge.tone}>{badge.label}</Badge>
                <span className="text-xs text-zinc-500">{s.transport}{s.oauth ? " · OAuth" : ""}{s.url ? ` · ${s.url}` : ""}{s.source === "file" ? " · mcp.json" : ""}</span>
                {s.authorization_url && <a className="text-xs underline" href={s.authorization_url} target="_blank" rel="noopener noreferrer">Authorize</a>}
                {s.tools.length > 0 && (
                  <button type="button" className="text-xs text-zinc-500 underline" onClick={() => setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))}>
                    {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}
                  </button>
                )}
                <span className="ml-auto flex gap-1">
                  {actions.includes("connect") && <Button variant="secondary" disabled={busy} onClick={() => connect.mutate(s.name)}>{s.oauth && s.status === "needs_auth" ? "Connect & authorize" : "Connect"}</Button>}
                  {actions.includes("reconnect") && <Button variant="secondary" disabled={busy} onClick={() => connect.mutate(s.name)}>Reconnect</Button>}
                  {actions.includes("disconnect") && <Button variant="secondary" disabled={busy} onClick={() => disconnect.mutate(s.name)}>Disconnect</Button>}
                  {actions.includes("forget") && <Button variant="secondary" disabled={busy} onClick={() => confirm(`Forget the stored credentials for ${s.name}?`) && forget.mutate(s.name)}>Forget credentials</Button>}
                  {actions.includes("remove") && <Button variant="danger" disabled={busy} onClick={() => confirm(`Remove ${s.name} and forget its credentials?`) && remove.mutate(s.name)}>Remove</Button>}
                </span>
              </div>
              {s.status === "authorizing" && <p className="text-xs text-amber-600">A browser tab was opened to authorize. If it did not appear, click Connect again and allow pop-ups.</p>}
              {s.error && <p className="text-xs text-red-600">{s.error}</p>}
              {open[s.name] && <p className="font-mono text-xs text-zinc-500">{s.tools.join(", ")}</p>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function AddMcpServerDialog({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const errors = validateNewMcpServer(name, url);
  const add = useMutation({ mutationFn: () => Api.addMcpServer({ name: name.trim(), url: url.trim() }), onSuccess: onAdded });
  const submit = () => { setTouched(true); if (Object.keys(errors).length === 0) add.mutate(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="add-mcp-title">
      <form className="w-full max-w-lg space-y-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-zinc-800 dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="flex items-start justify-between">
          <h2 id="add-mcp-title" className="text-lg font-semibold">Add MCP server</h2>
          <button type="button" aria-label="Close" className="text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200" onClick={onClose}>✕</button>
        </div>
        <p className="text-sm text-zinc-500">Connect your bots to a remote MCP server's tools. Local (stdio) servers and servers that need a secret header are configured in <code>mcp.json</code> instead.</p>
        <div className="space-y-1">
          <Input value={name} placeholder="Name" autoFocus onChange={(e) => setName(e.target.value)} />
          <p className="text-xs text-zinc-500">Shown in the servers list; tools appear as <code>{name.trim() || "name"}__tool</code>.</p>
          {touched && errors.name && <p className="text-xs text-red-600">{errors.name}</p>}
        </div>
        <div className="space-y-1">
          <Input value={url} placeholder="MCP server URL" onChange={(e) => setUrl(e.target.value)} />
          <p className="text-xs text-zinc-500">The HTTPS address where the server accepts MCP requests, for example https://mcp.example.com/mcp.</p>
          {touched && errors.url && <p className="text-xs text-red-600">{errors.url}</p>}
        </div>
        <p className="text-xs text-zinc-500">Only add servers from developers you trust. OpenBot does not control which tools a server exposes or what they do, and every bot you give those tools acts with whatever access you authorize. Mark tools that write as needing approval in the bot editor.</p>
        <ErrorText error={add.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={add.isPending || (touched && Object.keys(errors).length > 0)}>{add.isPending ? "Adding…" : "Continue"}</Button>
        </div>
      </form>
    </div>
  );
}
