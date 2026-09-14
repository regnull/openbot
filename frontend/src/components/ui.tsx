import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

const base = "rounded-md border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:bg-zinc-950";
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={`${base} w-full border-zinc-300 dark:border-zinc-700 ${p.className ?? ""}`} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={`${base} w-full border-zinc-300 font-mono dark:border-zinc-700 ${p.className ?? ""}`} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={`${base} w-full border-zinc-300 dark:border-zinc-700 ${p.className ?? ""}`} />;

const variants = {
  primary: "bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50",
  secondary: "border border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800 disabled:opacity-50",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:opacity-50",
};
export const Button = ({ variant = "primary", className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) =>
  <button {...p} className={`rounded-md px-3 py-2 text-sm font-medium ${variants[variant]} ${className}`} />;

export const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) => (
  <label className="block space-y-1"><span className="text-sm font-medium">{label}</span>{children}{hint && <span className="block text-xs text-zinc-500">{hint}</span>}</label>
);
export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) =>
  <div className={`rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 ${className}`}>{children}</div>;

const toneClasses = {
  zinc: "bg-zinc-100 text-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-200",
  green: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  red: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
  blue: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
};
export const Badge = ({ children, tone = "zinc" }: { children: ReactNode; tone?: keyof typeof toneClasses }) =>
  <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}>{children}</span>;
export const Spinner = () => <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-400 border-t-transparent" />;
export const ErrorText = ({ error }: { error: unknown }) => error ? <p className="text-sm text-red-600">{String((error as Error).message ?? error)}</p> : null;
