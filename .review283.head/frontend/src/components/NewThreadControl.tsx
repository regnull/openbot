import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Api } from "../api/client";
import { ChevronDownIcon, PlusIcon } from "./icons";

/** Split action for creating a default thread or opening the customization flow. */
export default function NewThreadControl({ collapsed = false }: { collapsed?: boolean }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const create = useMutation({
    mutationFn: () => Api.createThread({ handles: [] }),
    onSuccess: (thread) => {
      qc.invalidateQueries({ queryKey: ["threads"] });
      nav(`/threads/${thread.id}`);
    },
  });

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => create.mutate()}
        disabled={create.isPending}
        className="mt-2 flex h-9 w-9 items-center justify-center rounded-ui border border-accent bg-accent text-on-accent hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
        title="New thread"
        aria-label="New thread"
      >
        <PlusIcon className="h-4 w-4" />
      </button>
    );
  }

  return (
    <div ref={menuRef} className="relative flex">
      <button
        type="button"
        onClick={() => create.mutate()}
        disabled={create.isPending}
        className="flex h-9 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-l-ui border border-r-0 border-accent bg-accent px-3 text-[13px] font-medium leading-5 text-on-accent transition-colors hover:border-accent-strong hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="New thread"
      >
        <PlusIcon className="h-3.5 w-3.5" />
        New thread
      </button>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={create.isPending}
        className="flex h-9 w-8 shrink-0 items-center justify-center rounded-r-ui border border-l border-accent bg-accent text-on-accent transition-colors hover:border-accent-strong hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="New thread options"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <ChevronDownIcon className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 min-w-full overflow-hidden rounded-ui border border-line bg-surface p-1 shadow-[0_12px_30px_-12px_rgb(0_0_0/0.6)]" role="menu" aria-label="New thread options">
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); create.mutate(); }}
            className="block w-full whitespace-nowrap rounded-ui px-3 py-2 text-left text-xs text-fg hover:bg-sunken"
          >
            Start thread
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); nav("/threads"); }}
            className="block w-full whitespace-nowrap rounded-ui px-3 py-2 text-left text-xs text-fg hover:bg-sunken"
          >
            Set up thread
          </button>
        </div>
      )}
    </div>
  );
}
