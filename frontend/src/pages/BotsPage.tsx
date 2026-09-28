import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Api } from "../api/client";
import BotActivityIndicator from "../components/BotActivityIndicator";
import BotIcon from "../components/BotIcon";
import { Badge, Button, Card, EmptyState, ErrorText, PageTitle, Spinner } from "../components/ui";
import { PlusIcon } from "../components/icons";

export default function BotsPage() {
  const qc = useQueryClient();
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots, refetchInterval: 10_000 });
  const catalog = useQuery({ queryKey: ["bot-catalog"], queryFn: Api.listBotCatalog });
  const install = useMutation({ mutationFn: Api.installBotCatalogEntry, onSuccess: () => qc.invalidateQueries({ queryKey: ["bots"] }) });
  const existing = new Set(bots.data?.map((b) => b.handle));
  return (
    <div className="space-y-5">
      <PageTitle actions={<Link to="/bots/new" className="inline-flex h-9 items-center gap-1.5 rounded-ui border border-accent bg-accent px-3 text-[13px] font-medium leading-none text-on-accent transition-colors hover:border-accent-strong hover:bg-accent-strong"><PlusIcon className="h-3.5 w-3.5" /> New bot</Link>}>Bots</PageTitle>
      <ErrorText error={bots.error ?? catalog.error ?? install.error} />
      {bots.isLoading && <Spinner />}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {bots.data?.map((b) => (
          <Link key={b.id} to={`/bots/${b.id}`} className="group"><Card className="flex h-full flex-col gap-3 transition-colors group-hover:border-line-strong"><div className="flex items-start justify-between gap-3"><div className="flex min-w-0 items-center gap-2.5"><BotIcon icon={b.icon} /><div className="min-w-0"><div className="truncate text-[13px] font-medium">{b.name}</div><div className="truncate text-xs text-muted">@{b.handle}</div></div></div><div className="flex shrink-0 items-center gap-2 pt-1"><BotActivityIndicator active={b.active} showLabel />{!b.enabled && <Badge tone="amber">disabled</Badge>}</div></div><p className="line-clamp-3 flex-1 font-sans text-[13px] leading-relaxed text-muted">{b.description || "No description yet."}</p><div className="flex flex-wrap gap-x-3 text-[11px] leading-4 text-faint"><span>{b.provider === "auto" ? "auto model" : `${b.provider}/${b.model}`}</span><span>{b.tool_names.length} tool{b.tool_names.length === 1 ? "" : "s"}{b.approval_tools.length ? `, ${b.approval_tools.length} need approval` : ""}</span></div></Card></Link>
        ))}
        {bots.data?.length === 0 && <EmptyState className="sm:col-span-2 lg:col-span-3">No bots yet. Choose one from the catalog below, or create one.</EmptyState>}
      </div>
      <section className="space-y-3">
        <h2 className="text-sm font-medium">Bot catalog</h2>
        <p className="text-xs text-muted">Repository-backed bots include reviewed instructions and tool grants. Installing adds a disabled? No—catalog bots follow the normal enabled bot lifecycle and never starts external services.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {catalog.data?.map((entry) => { const added = existing.has(entry.handle); return <Card key={entry.id} className="flex flex-col gap-2"><div className="flex items-center gap-2"><BotIcon icon={entry.icon} /><div><div className="text-[13px] font-medium">{entry.name}</div><div className="text-xs text-muted">@{entry.handle}</div></div></div><p className="flex-1 text-xs leading-relaxed text-muted">{entry.description}</p><Button type="button" variant="secondary" disabled={added || install.isPending} onClick={() => install.mutate({ id: entry.id })}>{added ? "Already added" : install.isPending ? "Adding…" : "Add bot"}</Button></Card>; })}
        </div>
      </section>
    </div>
  );
}
