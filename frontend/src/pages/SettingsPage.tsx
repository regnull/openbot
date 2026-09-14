import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Api, getApiKey, setApiKey } from "../api/client";
import { Badge, Button, Card, ErrorText, Field, Input } from "../components/ui";

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
