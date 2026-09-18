export interface WorkingDirectoryValidation {
  ok: boolean;
  value: string | null;
  error: string | null;
}

export function normalizeWorkingDirectory(input: string): WorkingDirectoryValidation {
  const trimmed = input.trim();
  if (!trimmed || trimmed === ".") return { ok: true, value: null, error: null };
  if ([...trimmed].some((char) => char.charCodeAt(0) < 32)) {
    return { ok: false, value: null, error: "Working directory cannot contain control characters." };
  }
  const homeRelative = trimmed === "~" || trimmed.startsWith("~/") || trimmed.startsWith("~\\");
  if (!homeRelative && (trimmed.startsWith("/") || /^[A-Za-z]:[\\/]/.test(trimmed) || trimmed.startsWith("\\\\"))) {
    return { ok: false, value: null, error: "Working directory must be relative to the workspace root." };
  }
  const path = homeRelative ? trimmed.slice(1) : trimmed;
  const parts = path.split(/[\\/]+/).filter((part) => part.length > 0 && part !== ".");
  if (parts.some((part) => part === "..")) {
    return { ok: false, value: null, error: "Working directory cannot contain '..'." };
  }
  return { ok: true, value: homeRelative ? `~/${parts.join("/")}`.replace(/^~\/$/, "~") : parts.join("/"), error: null };
}

/** Where a directory picker should open: the typed path when it is a valid working directory, else the workspace root. */
export function initialPickerPath(typed: string): string {
  const v = normalizeWorkingDirectory(typed);
  return v.ok && v.value ? v.value : ".";
}
