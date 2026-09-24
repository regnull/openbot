/** Line icons, 24-unit grid, drawn with the current color. Keep strokes at 1.75 for the mono UI weight. */
import type { SVGProps } from "react";

const base = (p: SVGProps<SVGSVGElement>) => ({
  viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, ...p,
});
export const InboxIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></svg>;
export const ThreadsIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>;
export const BotsIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="9" cy="16" r="1" /><circle cx="15" cy="16" r="1" /><path d="M8 11V7a4 4 0 1 1 8 0v4" /></svg>;
export const SettingsIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>;
export const PlusIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>;
export const FolderIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>;
export const ChevronLeftIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="m15 18-6-6 6-6" /></svg>;
export const ChevronRightIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="m9 18 6-6-6-6" /></svg>;
export const ChevronDownIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="m6 9 6 6 6-6" /></svg>;
export const PanelLeftCloseIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M16 9l-3 3 3 3" /></svg>;
export const PanelLeftOpenIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M13 9l3 3-3 3" /></svg>;
export const SunIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" /></svg>;
export const MoonIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z" /></svg>;
export const MonitorIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>;
export const CloseIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M18 6 6 18M6 6l12 12" /></svg>;
export const ArrowUpIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M12 19V5M5 12l7-7 7 7" /></svg>;
export const MoreIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></svg>;
export const ExternalIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>;
export const SendIcon = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
