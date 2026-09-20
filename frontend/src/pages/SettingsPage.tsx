import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Api, getApiKey, setApiKey } from "../api/client";
import type { AppSetting, McpServer, McpServerInput } from "../api/types";
import { Badge, Button, Card, Dialog, ErrorText, Field, Hint, Input, PageTitle, SectionTitle, Textarea } from "../components/ui";
import { dismissSaveNotification, notifySave, useSaveMutation } from "../lib/saveNotifications";
import { formatSettingValue, groupSettings, parseSettingInput, type SettingGroup } from "../lib/appSettings";
import { formatArgs, formatKeyValues, mcpActions, mcpInFlight, mcpStatusBadge, parseArgs, parseKeyValues, validateNewMcpServer, type McpTransport } from "../lib/mcpServers";

const emptyExt = { handle: "", name: "", webhook_url: "", webhook_secret: "" };
const Code = ({ children }: { children: React.ReactNode }) => <code className="rounded-ui border border-line bg-sunken px-1 text-[11px]">{children}</code>;

export default function SettingsPage() {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: Api.getProviders });
  const tools = useQuery({ queryKey: ["tools"], queryFn: Api.listTools });
  const actors = useQuery({ queryKey: ["actors"], queryFn: Api.listActors });
  const [key, setKey] = useState(getApiKey());
  const [keyError, setKeyError] = useState<Error | null>(null);
  const [ext, setExt] = useState(emptyExt);
  const createExt = useSaveMutation({
    mutationFn: () => Api.createActor({ handle: ext.handle, name: ext.name, webhook_url: ext.webhook_url || null, webhook_secret: ext.webhook_secret || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["actors"] }); setExt(emptyExt); },
  }, "External actor added");
  const delExt = useSaveMutation({ mutationFn: (id: string) => Api.deleteActor(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["actors"] }) }, "External actor removed");
  const externals = actors.data?.filter((a) => a.kind === "external") ?? [];
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageTitle>Settings</PageTitle>

      <RuntimeSettings />

      <McpServersCard />

      <Card className="space-y-3">
        <SectionTitle>Providers</SectionTitle>
        <ErrorText error={providers.error} />
        <div className="flex flex-wrap gap-1.5">
          {providers.data?.providers.map((p) => <Badge key={p.id} tone={p.configured ? "green" : "zinc"}>{p.id}: {p.configured ? "configured" : "no key"}</Badge>)}
        </div>
        <Hint>Embeddings: <span className="font-mono text-xs">{providers.data?.embedding_model}</span>, {providers.data?.embeddings_configured ? "configured." : "not configured, so memory search is by recency only."}</Hint>
        <Hint className="text-xs">Keys set in the server environment (.env) are the defaults; values saved above override them. Restart the server after changing environment keys.</Hint>
      </Card>

      <Card className="space-y-3">
        <SectionTitle>External actors</SectionTitle>
        <Hint>External systems post as themselves via the API and receive their inbox by signed webhook.</Hint>
        <ul className="divide-y divide-line text-[13px]">
          {externals.map((a) => (
            <li key={a.id} className="flex items-center gap-3 py-2">
              <span>@{a.handle}</span>
              <span className="font-sans text-muted">{a.name}</span>
              <span className="truncate text-xs text-faint">{a.webhook_url ?? "polling only"}</span>
              <Button variant="secondary" size="sm" className="ml-auto" onClick={() => delExt.mutate(a.id)} disabled={delExt.isPending}>Delete</Button>
            </li>
          ))}
          {externals.length === 0 && <li className="py-2 text-xs text-faint">None yet.</li>}
        </ul>
        <ErrorText error={delExt.error} />
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); createExt.mutate(); }}>
          <Field label="Handle"><Input value={ext.handle} onChange={(e) => setExt({ ...ext, handle: e.target.value })} pattern="[a-z0-9_\-]{2,32}" required /></Field>
          <Field label="Name"><Input value={ext.name} onChange={(e) => setExt({ ...ext, name: e.target.value })} required /></Field>
          <Field label="Webhook URL (optional)"><Input value={ext.webhook_url} onChange={(e) => setExt({ ...ext, webhook_url: e.target.value })} /></Field>
          <Field label="Webhook secret (optional)"><Input value={ext.webhook_secret} onChange={(e) => setExt({ ...ext, webhook_secret: e.target.value })} /></Field>
          <div className="space-y-2 sm:col-span-2"><ErrorText error={createExt.error} /><Button type="submit" variant="secondary" disabled={createExt.isPending}>Add external actor</Button></div>
        </form>
      </Card>

      <Card className="space-y-3">
        <SectionTitle>Tools</SectionTitle>
        <ErrorText error={tools.error} />
        {tools.data?.errors.map((e) => <p key={e.file} className="text-xs text-danger">{e.file}: {e.error}</p>)}
        <ul className="divide-y divide-line">
          {tools.data?.tools.map((t) => (
            <li key={t.name} className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-[13px]"><span>{t.name}</span> <span className="min-w-0 flex-1 font-sans text-xs text-muted">{t.description}</span> <span className="text-[11px] text-faint">{t.source}</span></li>
          ))}
        </ul>
      </Card>

      <Card className="space-y-3">
        <SectionTitle>API key</SectionTitle>
        <Hint>Only needed when the server sets OPENBOT_API_KEY. Stored in this browser.</Hint>
        <div className="flex gap-2">
          <Input value={key} onChange={(e) => setKey(e.target.value)} placeholder="X-API-Key" />
          <Button variant="secondary" onClick={() => {
            dismissSaveNotification();
            try {
              setApiKey(key.trim()); setKeyError(null); notifySave("API key saved in this browser");
              qc.invalidateQueries();
            } catch {
              setKeyError(new Error("Could not save the API key. Check your browser storage settings."));
              notifySave("Could not save the API key.", "error");
            }
          }}>Save</Button>
        </div>
        <ErrorText error={keyError} />
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
  const refresh = (rows: AppSetting[]) => {
    qc.setQueryData(["settings"], rows); setDrafts({}); setErrors({});
    // Provider keys and embeddings change what the Providers card and the setup gate report.
    qc.invalidateQueries({ queryKey: ["providers"] }); qc.invalidateQueries({ queryKey: ["setup-status"] });
  };
  const save = useSaveMutation({ mutationFn: (updates: Record<string, unknown>) => Api.patchSettings(updates), onSuccess: refresh }, "Settings saved");
  const reset = useSaveMutation({ mutationFn: (key: string) => Api.resetSetting(key), onSuccess: refresh }, "Setting reset to default");
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
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle className="min-w-40 flex-1">{group.name}</SectionTitle>
        <span className="font-sans text-xs text-faint">Takes effect on the next run. Environment values are the defaults.</span>
      </div>
      <div className="divide-y divide-line">
        {group.items.map((item) => {
          const current = formatSettingValue(item.type, item.value);
          const draft = item.key in drafts ? drafts[item.key] : current;
          const edited = item.key in drafts;
          const setDraft = (v: string) => setDrafts((d) => { const n = { ...d }; if (v === current) delete n[item.key]; else n[item.key] = v; return n; });
          return (
            <div key={item.key} className="grid gap-2 py-3 sm:grid-cols-[1fr_14rem]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="font-medium">{item.label}</span>
                  {item.overridden && <Badge tone="amber">overridden</Badge>}
                  {item.overridden && (
                    <button type="button" className="text-xs text-muted underline underline-offset-2 hover:text-fg" disabled={reset.isPending} onClick={() => reset.mutate(item.key)}>
                      reset to {formatSettingValue(item.type, item.default) || "empty"}
                    </button>
                  )}
                </div>
                <div className="font-sans text-xs text-muted">{item.description}</div>
                {errors[item.key] && <div className="text-xs text-danger">{errors[item.key]}</div>}
              </div>
              <div className="flex items-center">
                {item.type === "bool" ? (
                  <label className="flex items-center gap-2 text-[13px]">
                    <input type="checkbox" checked={draft === "true"} onChange={(e) => setDraft(String(e.target.checked))} /> {draft === "true" ? "on" : "off"}
                  </label>
                ) : item.type === "secret" ? (
                  <div className="w-full space-y-1">
                    <Input type="password" autoComplete="off" value={edited ? draft : ""} placeholder={item.is_set ? "set (enter a new value to replace)" : "not set"}
                      className={edited ? "border-warn" : ""} onChange={(e) => setDraft(e.target.value)} />
                    <div className="text-[11px] text-faint">{item.is_set ? "Stored encrypted." : "Not set."}</div>
                  </div>
                ) : (
                  <Input value={draft} inputMode={item.type === "int" || item.type === "float" ? "decimal" : undefined}
                    className={edited ? "border-warn" : ""} onChange={(e) => setDraft(e.target.value)}
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
  const disconnect = useSaveMutation({ mutationFn: (name: string) => Api.disconnectMcpServer(name), onSuccess: refresh }, "MCP server disconnected");
  const forget = useSaveMutation({ mutationFn: (name: string) => Api.forgetMcpCredentials(name), onSuccess: refresh }, "MCP credentials removed");
  const remove = useSaveMutation({ mutationFn: (name: string) => Api.removeMcpServer(name), onSuccess: refresh }, "MCP server removed");
  const toggleEnabled = useSaveMutation({ mutationFn: (s: McpServer) => Api.updateMcpServer(s.name, { enabled: !s.enabled }), onSuccess: refresh }, "MCP server settings saved");
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
    <Card className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <SectionTitle className="flex-1">MCP servers</SectionTitle>
        <Button variant="secondary" size="sm" onClick={() => setDialog({ mode: "add" })}>Add server</Button>
      </div>
      <Hint>Tools from Model Context Protocol servers, remote (HTTPS, OAuth when the server asks) or local (a command run over stdio). Tools appear in the tool list as <Code>server__tool</Code>; grant them per bot in the bot editor, by server or one at a time.</Hint>
      {dialog && <McpServerDialog server={dialog.mode === "edit" ? dialog.server : undefined} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); refresh(); }} />}
      <ErrorText error={servers.error ?? connect.error ?? disconnect.error ?? forget.error ?? remove.error ?? toggleEnabled.error} />
      {servers.data?.length === 0 && <p className="text-xs text-faint">No servers yet.</p>}
      <ul className="divide-y divide-line text-[13px]">
        {servers.data?.map((s: McpServer) => {
          const badge = mcpStatusBadge(s);
          const actions = mcpActions(s);
          const inFlight = s.status === "connecting" || s.status === "authorizing";
          return (
            <li key={s.name} className="space-y-1.5 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{s.name}</span>
                <Badge tone={badge.tone} pulse={inFlight}>{badge.label}</Badge>
                <span className="truncate text-xs text-faint">{s.transport === "http" ? `remote${s.oauth ? ", OAuth" : ""}  ${s.url ?? ""}` : `local  ${s.command ?? ""} ${formatArgs(s.args)}`}</span>
                {s.authorization_url && <a className="text-xs underline underline-offset-2 hover:text-fg" href={s.authorization_url} target="_blank" rel="noopener noreferrer">Authorize</a>}
                {s.tools.length > 0 && (
                  <button type="button" className="text-xs text-muted underline underline-offset-2 hover:text-fg" aria-expanded={!!open[s.name]} onClick={() => setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))}>
                    {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}
                  </button>
                )}
                <span className="ml-auto flex flex-wrap gap-1">
                  {actions.includes("connect") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => connect.mutate(s.name)}>{s.oauth && s.status === "needs_auth" ? "Connect & authorize" : "Connect"}</Button>}
                  {actions.includes("reconnect") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => connect.mutate(s.name)}>Reconnect</Button>}
                  {actions.includes("disconnect") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => disconnect.mutate(s.name)}>Disconnect</Button>}
                  {actions.includes("forget") && <Button variant="secondary" size="sm" disabled={busy} onClick={() => confirm(`Forget the stored credentials for ${s.name}?`) && forget.mutate(s.name)}>Forget credentials</Button>}
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => setDialog({ mode: "edit", server: s })}>Edit</Button>
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => toggleEnabled.mutate(s)}>{s.enabled ? "Disable" : "Enable"}</Button>
                  <Button variant="danger" size="sm" disabled={busy} onClick={() => confirm(`Remove ${s.name} and forget its credentials?`) && remove.mutate(s.name)}>Remove</Button>
                </span>
              </div>
              {s.status === "authorizing" && <p className="font-sans text-xs text-warn">A browser tab was opened to authorize. If it did not appear, click Authorize above and allow pop-ups.</p>}
              {s.error && <p className="text-xs text-danger">{s.error}</p>}
              {open[s.name] && <p className="text-xs text-muted">{s.tools.join(", ")}</p>}
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
  const save = useSaveMutation({
    mutationFn: () => {
      const body: McpServerInput = transport === "http"
        ? { url: url.trim(), headers: kv.values }
        : { command: command.trim(), args: parseArgs(args), env: kv.values, cwd: cwd.trim() || null };
      return editing ? Api.updateMcpServer(server!.name, body) : Api.addMcpServer({ name: name.trim(), ...body });
    },
    onSuccess: onSaved,
  }, editing ? "MCP server settings saved" : "MCP server added");
  const submit = () => { setTouched(true); if (Object.keys(errors).length === 0 && !kv.error) save.mutate(); };
  const fieldError = (msg?: string | null) => touched && msg ? <p className="text-xs text-danger">{msg}</p> : null;
  const tab = (t: McpTransport, label: string) => (
    <button type="button" role="tab" aria-selected={transport === t} className={`h-7 rounded-[2px] px-3 text-xs transition-colors disabled:cursor-not-allowed ${transport === t ? "bg-sunken font-medium text-fg" : "text-muted hover:text-fg"}`}
      onClick={() => setTransport(t)} disabled={editing}>{label}</button>
  );
  return (
    <Dialog as="form" title={editing ? `Edit ${server!.name}` : "Add MCP server"} titleId="mcp-dialog-title" onClose={onClose} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <Hint>Connect your bots to an MCP server's tools. Use <Code>{"${VAR}"}</Code> in any value to read a secret from the server environment instead of storing it here.</Hint>
      <div role="tablist" className="inline-flex self-start rounded-ui border border-line p-0.5">{tab("http", "Remote (HTTPS)")}{tab("stdio", "Local (command)")}</div>
      {!editing && (
        <div className="space-y-1">
          <Input value={name} placeholder="Name" autoFocus onChange={(e) => setName(e.target.value)} />
          <Hint className="text-xs">Shown in the servers list; tools appear as <Code>{name.trim() || "name"}__tool</Code>.</Hint>
          {fieldError(errors.name)}
        </div>
      )}
      {transport === "http" ? (
        <>
          <div className="space-y-1">
            <Input value={url} placeholder="MCP server URL" autoFocus={editing} onChange={(e) => setUrl(e.target.value)} />
            <Hint className="text-xs">The HTTPS address where the server accepts MCP requests, for example https://mcp.example.com/mcp.</Hint>
            {fieldError(errors.url)}
          </div>
          <div className="space-y-1">
            <Textarea rows={2} value={headers} placeholder={"Authorization=Bearer ${LINEAR_KEY}"} onChange={(e) => setHeaders(e.target.value)} />
            <Hint className="text-xs">Optional headers, one <Code>Name=value</Code> per line. Leave a masked value as is to keep it. Without an Authorization header the server is asked to authorize with OAuth.</Hint>
            {fieldError(kv.error)}
          </div>
        </>
      ) : (
        <>
          <div className="space-y-1">
            <Input value={command} placeholder="Command, for example npx" autoFocus={editing} onChange={(e) => setCommand(e.target.value)} />
            {fieldError(errors.command)}
          </div>
          <Input value={args} placeholder="Arguments, for example -y @modelcontextprotocol/server-github" onChange={(e) => setArgs(e.target.value)} />
          <div className="space-y-1">
            <Textarea rows={2} value={env} placeholder={"GITHUB_TOKEN=${GITHUB_TOKEN}"} onChange={(e) => setEnv(e.target.value)} />
            <Hint className="text-xs">Environment for the process, one <Code>NAME=value</Code> per line, added to the server's own environment. Leave a masked value as is to keep it.</Hint>
            {fieldError(kv.error)}
          </div>
          <Input value={cwd} placeholder="Working directory (optional)" onChange={(e) => setCwd(e.target.value)} />
        </>
      )}
      <Hint className="text-xs">Only add servers from developers you trust. OpenBot does not control which tools a server exposes or what they do, and every bot you grant those tools acts with whatever access you provide. Mark tools that write as needing approval in the bot editor.</Hint>
      <ErrorText error={save.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={save.isPending || (touched && (Object.keys(errors).length > 0 || !!kv.error))}>{save.isPending ? "Saving…" : editing ? "Save" : "Continue"}</Button>
      </div>
    </Dialog>
  );
}
