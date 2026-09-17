import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Api } from "../api/client";
import SetupWizard from "./SetupWizard";
import { Spinner } from "./ui";

/** Shows the setup wizard instead of the app, on every load, until the minimum configuration is met. */
export default function SetupGate({ children }: { children: ReactNode }) {
  const status = useQuery({ queryKey: ["setup-status"], queryFn: Api.getSetupStatus, retry: false });
  if (status.isLoading) return <div className="flex min-h-screen items-center justify-center"><Spinner /></div>;
  // If the status cannot be fetched (backend down, unauthorized), let the existing gates handle it.
  if (!status.data || status.data.complete) return <>{children}</>;
  return <SetupWizard status={status.data} onDone={() => status.refetch()} />;
}
