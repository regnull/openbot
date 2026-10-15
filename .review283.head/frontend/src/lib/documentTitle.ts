const APP_NAME = "OpenBot";

export function setOpenBotTitle(page?: string | null) {
  const label = page?.trim();
  document.title = label ? `${label} — ${APP_NAME}` : APP_NAME;
}

export { APP_NAME };
