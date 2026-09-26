import { useEffect, useState, type ReactNode } from "react";
import { Button, ErrorText, Hint, Input } from "./ui";
import { getApiKey, setApiKey } from "../api/client";
import { logoSrc } from "../lib/desktop";

export default function ApiKeyGate({ children }: { children: ReactNode }) {
  const [error, setError] = useState<Error | null>(null);
  const [needKey, setNeedKey] = useState(false);
  const [value, setValue] = useState(getApiKey());
  useEffect(() => {
    const h = () => setNeedKey(true);
    window.addEventListener("openbot:unauthorized", h);
    return () => window.removeEventListener("openbot:unauthorized", h);
  }, []);
  if (!needKey) return <>{children}</>;
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form className="w-full max-w-sm space-y-4 rounded-ui border border-line bg-surface p-6"
        onSubmit={(e) => { e.preventDefault(); try { setApiKey(value.trim()); location.reload(); } catch { setError(new Error("Could not save the API key. Check your browser storage settings.")); } }}>
        <div className="flex items-center gap-2">
          <img src={logoSrc} alt="" className="h-5 w-5 rounded-[4px]" aria-hidden="true" />
          <h1 className="text-sm font-semibold">API key required</h1>
        </div>
        <Hint>This server has OPENBOT_API_KEY set. Paste it to continue. The key stays in this browser.</Hint>
        <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="X-API-Key" autoFocus />
        <ErrorText error={error} />
        <Button type="submit" className="w-full">Save key</Button>
      </form>
    </div>
  );
}
