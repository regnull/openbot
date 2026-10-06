import { useMemo, type ReactNode } from "react";

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
  const accessibleValue = loading ? "loading" : `${displayValue}${unit ? ` ${unit}` : ""}`;

  return (
    <span className="thread-odometer" role="img" aria-label={`${label}: ${accessibleValue}`}>
      <span className="thread-odometer-label" title={indicatorLabel ?? label}>
        {indicator ?? label}
      </span>
      <span className={`thread-odometer-value${loading ? " thread-odometer-loading" : ""}`} aria-hidden="true">
        {digits.map((character, index) => (
          <span className={/[0-9]/.test(character) ? "thread-odometer-digit" : "thread-odometer-separator"} key={`${index}-${character}`}>
            {character}
          </span>
        ))}
        {unit && <span className="thread-odometer-unit">{unit}</span>}
      </span>
    </span>
  );
}
