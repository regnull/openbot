import { useEffect, useState, type ReactNode } from "react";
import { getApiKey, setApiKey } from "../api/client";

export default function ApiKeyGate({ children }: { children: ReactNode }) {
  const [needKey, setNeedKey] = useState(false);
  const [value, setValue] = useState(getApiKey());
  useEffect(() => {
    const h = () => setNeedKey(true);
    window.addEventListener("openbot:unauthorized", h);
    return () => window.removeEventListener("openbot:unauthorized", h);
  }, []);
  if (!needKey) return <>{children}</>;
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <form className="w-full max-w-sm space-y-3 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
        onSubmit={(e) => { e.preventDefault(); setApiKey(value.trim()); location.reload(); }}>
        <h1 className="text-lg font-semibold">API key required</h1>
        <p className="text-sm text-zinc-500">This server has OPENBOT_API_KEY set. Paste it to continue.</p>
        <input className="w-full rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950" value={value} onChange={(e) => setValue(e.target.value)} placeholder="X-API-Key" />
        <button className="w-full rounded-md bg-zinc-900 px-3 py-2 text-white dark:bg-zinc-100 dark:text-zinc-900">Save</button>
      </form>
    </div>
  );
}
