export const DEFAULT_BOTTOM_THRESHOLD_PX = 80;

type ScrollMetrics = Pick<HTMLElement, "clientHeight" | "scrollHeight" | "scrollTop">;

export function isNearBottom(element: ScrollMetrics, thresholdPx = DEFAULT_BOTTOM_THRESHOLD_PX) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= thresholdPx;
}

export function scrollToBottom(element: HTMLElement) {
  element.scrollTo({ top: element.scrollHeight });
}
