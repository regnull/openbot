import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Api, getApiKey, setApiKey } from "../api/client";
import type { AppSetting, McpServer, McpServerInput } from "../api/types";
import { Badge, Button, Card, ErrorText, Field, Input, Textarea } from "../components/ui";
import { formatSettingValue, groupSettings, parseSettingInput, type SettingGroup } from "../lib/appSettings";
import { formatArgs, formatKeyValues, mcpActions, mcpInFlight, mcpStatusBadge, parseArgs, parseKeyValues, validateNewMcpServer, type McpTransport } from "../lib/mcpServers";

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
  const toggleEnabled = useMutation({ mutationFn: (s: McpServer) => Api.updateMcpServer(s.name, { enabled: !s.enabled }), onSuccess: refresh });
  const busy = connect.isPending || disconnect.isPending || forget.isPending || remove.isPending || toggleEnabled.isPending;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [dialog, setDialog] = useState<null | { mode: "add" } | { mode: "edit"; server: McpServer }>(null);
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
        <Button variant="secondary" onClick={() => setDialog({ mode: "add" })}>Add server</Button>
      </div>
      <p className="text-sm text-zinc-500">Tools from Model Context Protocol servers, remote (HTTPS, OAuth when the server asks) or local (a command run over stdio). Tools appear in the tool list as <code>server__tool</code>; grant them per bot in the bot editor, by server or one at a time.</p>
      {dialog && <McpServerDialog server={dialog.mode === "edit" ? dialog.server : undefined} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); refresh(); }} />}
      <ErrorText error={servers.error ?? connect.error ?? disconnect.error ?? forget.error ?? remove.error ?? toggleEnabled.error} />
      {servers.data?.length === 0 && <p className="text-sm text-zinc-500">No servers yet.</p>}
      <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
        {servers.data?.map((s: McpServer) => {
          const badge = mcpStatusBadge(s);
          const actions = mcpActions(s);
          return (
            <li key={s.name} className="space-y-1 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{s.name}</span>
                <Badge tone={badge.tone}>{badge.label}</Badge>
                <span className="truncate text-xs text-zinc-500">{s.transport === "http" ? `remote${s.oauth ? " · OAuth" : ""} · ${s.url ?? ""}` : `local · ${s.command ?? ""} ${formatArgs(s.args)}`}</span>
                {s.authorization_url && <a className="text-xs underline" href={s.authorization_url} target="_blank" rel="noopener noreferrer">Authorize</a>}
                {s.tools.length > 0 && (
                  <button type="button" className="text-xs text-zinc-500 underline" onClick={() => setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))}>
                    {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}
                  </button>
                )}
                <span className="ml-auto flex flex-wrap gap-1">
                  {actions.includes("connect") && <Button variant="secondary" disabled={busy} onClick={() => connect.mutate(s.name)}>{s.oauth && s.status === "needs_auth" ? "Connect & authorize" : "Connect"}</Button>}
                  {actions.includes("reconnect") && <Button variant="secondary" disabled={busy} onClick={() => connect.mutate(s.name)}>Reconnect</Button>}
                  {actions.includes("disconnect") && <Button variant="secondary" disabled={busy} onClick={() => disconnect.mutate(s.name)}>Disconnect</Button>}
                  {actions.includes("forget") && <Button variant="secondary" disabled={busy} onClick={() => confirm(`Forget the stored credentials for ${s.name}?`) && forget.mutate(s.name)}>Forget credentials</Button>}
                  <Button variant="secondary" disabled={busy} onClick={() => setDialog({ mode: "edit", server: s })}>Edit</Button>
                  <Button variant="secondary" disabled={busy} onClick={() => toggleEnabled.mutate(s)}>{s.enabled ? "Disable" : "Enable"}</Button>
                  <Button variant="danger" disabled={busy} onClick={() => confirm(`Remove ${s.name} and forget its credentials?`) && remove.mutate(s.name)}>Remove</Button>
                </span>
              </div>
              {s.status === "authorizing" && <p className="text-xs text-amber-600">A browser tab was opened to authorize. If it did not appear, click Authorize above and allow pop-ups.</p>}
              {s.error && <p className="text-xs text-red-600">{s.error}</p>}
              {open[s.name] && <p className="font-mono text-xs text-zinc-500">{s.tools.join(", ")}</p>}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function McpServerDialog({ server, onClose, onSaved }: { server?: McpServer; onClose: () => void; onSaved: () => void }) {
  const editing = !!server;
  const [transport, setTransport] = useState<McpTransport>(server?.transport ?? "http");
  const [name, setName] = useState(server?.name ?? "");
  const [url, setUrl] = useState(server?.url ?? "");
  const [headers, setHeaders] = useState(formatKeyValues(server?.headers ?? {}));
  const [command, setCommand] = useState(server?.command ?? "");
  const [args, setArgs] = useState(formatArgs(server?.args ?? []));
  const [env, setEnv] = useState(formatKeyValues(server?.env ?? {}));
  const [cwd, setCwd] = useState(server?.cwd ?? "");
  const [touched, setTouched] = useState(false);
  const errors = validateNewMcpServer(name, url, transport, command);
  const kv = parseKeyValues(transport === "http" ? headers : env);
  const save = useMutation({
    mutationFn: () => {
      const body: McpServerInput = transport === "http"
        ? { url: url.trim(), headers: kv.values }
        : { command: command.trim(), args: parseArgs(args), env: kv.values, cwd: cwd.trim() || null };
      return editing ? Api.updateMcpServer(server!.name, body) : Api.addMcpServer({ name: name.trim(), ...body });
    },
    onSuccess: onSaved,
  });
  const submit = () => { setTouched(true); if (Object.keys(errors).length === 0 && !kv.error) save.mutate(); };
  const tab = (t: McpTransport, label: string) => (
    <button type="button" className={`rounded-md px-3 py-1 text-sm ${transport === t ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"}`}
      onClick={() => setTransport(t)} disabled={editing}>{label}</button>
  );
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="mcp-dialog-title">
      <form className="w-full max-w-lg space-y-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-zinc-800 dark:bg-zinc-900"
        onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="flex items-start justify-between">
          <h2 id="mcp-dialog-title" className="text-lg font-semibold">{editing ? `Edit ${server!.name}` : "Add MCP server"}</h2>
          <button type="button" aria-label="Close" className="text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200" onClick={onClose}>✕</button>
        </div>
        <p className="text-sm text-zinc-500">Connect your bots to an MCP server's tools. Use <code>{"${VAR}"}</code> in any value to read a secret from the server environment instead of storing it here.</p>
        <div className="flex gap-1">{tab("http", "Remote (HTTPS)")}{tab("stdio", "Local (command)")}</div>
        {!editing && (
          <div className="space-y-1">
            <Input value={name} placeholder="Name" autoFocus onChange={(e) => setName(e.target.value)} />
            <p className="text-xs text-zinc-500">Shown in the servers list; tools appear as <code>{name.trim() || "name"}__tool</code>.</p>
            {touched && errors.name && <p className="text-xs text-red-600">{errors.name}</p>}
          </div>
        )}
        {transport === "http" ? (
          <>
            <div className="space-y-1">
              <Input value={url} placeholder="MCP server URL" autoFocus={editing} onChange={(e) => setUrl(e.target.value)} />
              <p className="text-xs text-zinc-500">The HTTPS address where the server accepts MCP requests, for example https://mcp.example.com/mcp.</p>
              {touched && errors.url && <p className="text-xs text-red-600">{errors.url}</p>}
            </div>
            <div className="space-y-1">
              <Textarea rows={2} value={headers} placeholder={"Authorization=Bearer ${LINEAR_KEY}"} onChange={(e) => setHeaders(e.target.value)} />
              <p className="text-xs text-zinc-500">Optional headers, one <code>Name=value</code> per line. Leave a masked value as is to keep it. Without an Authorization header the server is asked to authorize with OAuth.</p>
              {touched && kv.error && <p className="text-xs text-red-600">{kv.error}</p>}
            </div>
          </>
        ) : (
          <>
            <div className="space-y-1">
              <Input value={command} placeholder="Command, for example npx" autoFocus={editing} onChange={(e) => setCommand(e.target.value)} />
              {touched && errors.command && <p className="text-xs text-red-600">{errors.command}</p>}
            </div>
            <Input value={args} placeholder="Arguments, for example -y @modelcontextprotocol/server-github" onChange={(e) => setArgs(e.target.value)} />
            <div className="space-y-1">
              <Textarea rows={2} value={env} placeholder={"GITHUB_TOKEN=${GITHUB_TOKEN}"} onChange={(e) => setEnv(e.target.value)} />
              <p className="text-xs text-zinc-500">Environment for the process, one <code>NAME=value</code> per line, added to the server's own environment. Leave a masked value as is to keep it.</p>
              {touched && kv.error && <p className="text-xs text-red-600">{kv.error}</p>}
            </div>
            <Input value={cwd} placeholder="Working directory (optional)" onChange={(e) => setCwd(e.target.value)} />
          </>
        )}
        <p className="text-xs text-zinc-500">Only add servers from developers you trust. OpenBot does not control which tools a server exposes or what they do, and every bot you grant those tools acts with whatever access you provide. Mark tools that write as needing approval in the bot editor.</p>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={save.isPending || (touched && (Object.keys(errors).length > 0 || !!kv.error))}>{save.isPending ? "Saving…" : editing ? "Save" : "Continue"}</Button>
        </div>
      </form>
    </div>
  );
}
