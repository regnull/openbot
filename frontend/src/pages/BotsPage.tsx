import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Api } from "../api/client";
import BotActivityIndicator from "../components/BotActivityIndicator";
import BotIcon from "../components/BotIcon";
import { Badge, Button, Card, ErrorText, Spinner } from "../components/ui";

export default function BotsPage() {
  const bots = useQuery({ queryKey: ["bots"], queryFn: Api.listBots });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-xl font-semibold">Bots</h1><Link to="/bots/new"><Button>New bot</Button></Link></div>
      <ErrorText error={bots.error} />
      {bots.isLoading && <Spinner />}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {bots.data?.map((b) => (
          <Link key={b.id} to={`/bots/${b.id}`}>
            <Card className="h-full space-y-2 hover:border-blue-400">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2"><BotIcon icon={b.icon} /><span className="truncate font-semibold">{b.name}</span></div>
                <div className="flex shrink-0 items-center gap-2"><BotActivityIndicator active={b.active} showLabel />{!b.enabled && <Badge tone="amber">disabled</Badge>}</div>
              </div>
              <div className="text-sm text-zinc-500">@{b.handle} · {b.provider}/{b.model}</div>
              <p className="line-clamp-3 text-sm">{b.description || "No description"}</p>
              <div className="text-xs text-zinc-500">{b.tool_names.length} tools{b.approval_tools.length ? ` · ${b.approval_tools.length} need approval` : ""}</div>
            </Card>
          </Link>
        ))}
        {bots.data?.length === 0 && <p className="text-zinc-500">No bots yet. Create one, or set a provider key and restart to seed the demo team.</p>}
      </div>
    </div>
  );
}
