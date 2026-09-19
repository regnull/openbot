import { useMutation, type UseMutationOptions } from "@tanstack/react-query";

type Notice = { message: string; tone: "success" | "error" };
let current: Notice | null = null;
export const getSaveNotification = () => current;
const listeners = new Set<() => void>();
export const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function dismissSaveNotification() {
  current = null;
  listeners.forEach((listener) => listener());
}
export function notifySave(message: string, tone: Notice["tone"] = "success") {
  // One notification slot: repeated callbacks cannot stack duplicate popups.
  if (current?.message === message && current.tone === tone) return;
  current = { message, tone };
  listeners.forEach((listener) => listener());
}

/** Feedback belongs to the persistence result, not query refreshes or render effects. */
export function useSaveMutation<TData, TVariables = void>(
  options: UseMutationOptions<TData, Error, TVariables>, message: string,
) {
  return useMutation({
    ...options,
    onMutate: (...args) => { dismissSaveNotification(); return options.onMutate?.(...args); },
    onSuccess: (...args) => { notifySave(message); return options.onSuccess?.(...args); },
    onError: (...args) => {
      notifySave("Could not save changes. Please try again.", "error");
      return options.onError?.(...args);
    },
  });
}

