import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type ThreadOdometerProps = {
  label: string;
  value: number | null | undefined;
  prefix?: string;
  suffix?: string;
  unit?: string;
  indicator?: ReactNode;
  indicatorLabel?: string;
  loading?: boolean;
  format?: (value: number) => string;
};

const numberFormatter = new Intl.NumberFormat("en-US");

function formatValue(value: number, prefix: string, suffix: string, format?: (value: number) => string): string {
  const formatted = Number.isFinite(value) ? (format?.(value) ?? numberFormatter.format(value)) : "0";
  return `${prefix}${formatted}${suffix}`;
}

export default function ThreadOdometer({ label, value, prefix = "", suffix = "", unit = "", indicator, indicatorLabel, loading = false, format }: ThreadOdometerProps) {
  const displayValue = loading ? "—" : formatValue(value ?? 0, prefix, suffix, format);
  const digits = useMemo(() => [...displayValue], [displayValue]);
  const previousDisplay = useRef(displayValue);
  const [rollingDisplay, setRollingDisplay] = useState<string | null>(null);
  const changedDigits = rollingDisplay === null ? new Set<number>() : new Set(
    digits.map((character, index) => character !== rollingDisplay[index] ? index : -1).filter((index) => index >= 0),
  );
  const accessibleValue = loading ? "loading" : `${displayValue}${unit ? ` ${unit}` : ""}`;

  useEffect(() => {
    if (previousDisplay.current !== displayValue) {
      setRollingDisplay(previousDisplay.current);
      previousDisplay.current = displayValue;
      const timeout = window.setTimeout(() => setRollingDisplay(null), 360);
      return () => window.clearTimeout(timeout);
    }
    return undefined;
  }, [displayValue]);

  return (
    <span className="thread-odometer" role="img" aria-label={`${label}: ${accessibleValue}`}>
      <span className="thread-odometer-label" title={indicatorLabel ?? label}>
        {indicator ?? label}
      </span>
      <span className={`thread-odometer-value${loading ? " thread-odometer-loading" : ""}`} aria-hidden="true">
        {digits.map((character, index) => (
          <span className={/[0-9]/.test(character) ? `thread-odometer-digit${changedDigits.has(index) ? " thread-odometer-digit--rolling" : ""}` : "thread-odometer-separator"} key={`${index}-${character}`}>
            <span className="thread-odometer-digit-face">{character}</span>
          </span>
        ))}
        {unit && <span className="thread-odometer-unit">{unit}</span>}
      </span>
    </span>
  );
}
