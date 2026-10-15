const ZONED = /(?:Z|[+-]\d{2}:?\d{2})$/;

/**
 * The API serialises naive UTC datetimes ("2026-09-14T03:54:15.536421") alongside
 * zone-qualified ones ("...Z"), and JS reads a bare datetime as local time. Treat a
 * missing zone as UTC so hydrated and live messages agree on the clock.
 */
export const parseTs = (s: string): Date => new Date(ZONED.test(s) ? s : `${s}Z`);
