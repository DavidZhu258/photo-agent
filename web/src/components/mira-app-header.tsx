import Link from "next/link";
import type { ReactNode } from "react";

export type MiraHeaderChip = {
  id: string;
  label: string;
  value?: string;
};

type MiraAppHeaderProps = {
  subtitle?: string;
  chips?: MiraHeaderChip[];
  tripCount?: number;
  primaryAction: {
    href: string;
    label: string;
    icon: ReactNode;
  };
  iconAction?: {
    label: string;
    icon: ReactNode;
  };
  onChipClick?: (chipId: string) => void;
};

export function MiraAppHeader({
  subtitle = "识境",
  chips = [],
  tripCount = 0,
  primaryAction,
  iconAction,
  onChipClick,
}: MiraAppHeaderProps) {
  return (
    <header
      data-testid="mira-app-header"
      className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-neutral-200 bg-white px-4 py-2 pt-[calc(0.5rem+env(safe-area-inset-top))] sm:gap-4 sm:px-6 sm:py-3 sm:pt-[calc(0.75rem+env(safe-area-inset-top))]"
    >
      <div className="min-w-0">
        <h1
          data-testid="mira-app-title"
          className="truncate text-base font-semibold tracking-normal text-neutral-950"
        >
          Mira
        </h1>
        <p className="truncate text-xs leading-5 text-neutral-500">{subtitle}</p>
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            onClick={() => onChipClick?.(chip.id)}
            className={`h-8 max-w-[8.5rem] items-center rounded-full border border-neutral-200 bg-white px-3 text-xs font-medium text-neutral-700 shadow-sm transition hover:border-neutral-400 ${
              chip.value ? "inline-flex" : "hidden sm:inline-flex"
            }`}
          >
            <span className="truncate">{chip.value || chip.label}</span>
          </button>
        ))}
        {tripCount > 0 ? (
          <button
            type="button"
            className="inline-flex h-8 items-center gap-1 rounded-full border border-neutral-200 px-3 text-xs font-medium text-neutral-700"
          >
            Trip <span className="rounded-full bg-sky-600 px-1.5 py-0.5 text-[10px] text-white">{tripCount}</span>
          </button>
        ) : null}
        <Link
          data-testid="mira-header-primary-action"
          href={primaryAction.href}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-neutral-200 px-3 text-xs font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50"
        >
          <span className="grid size-4 place-items-center">{primaryAction.icon}</span>
          <span>{primaryAction.label}</span>
        </Link>
        {iconAction ? (
          <button
            data-testid="mira-header-icon-action"
            type="button"
            aria-label={iconAction.label}
            className="grid size-8 place-items-center rounded-full border border-neutral-200 text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50"
          >
            {iconAction.icon}
          </button>
        ) : null}
      </div>
    </header>
  );
}
