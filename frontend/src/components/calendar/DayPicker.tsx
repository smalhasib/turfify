"use client";

import { addDaysIso, formatDayHeader } from "@/lib/calendar";
import { cn } from "@/lib/cn";

type Props = {
  start: string; // first day in window (ISO)
  selected: string;
  windowDays?: number;
  onSelect: (iso: string) => void;
};

export function DayPicker({ start, selected, windowDays = 7, onSelect }: Props) {
  const days = Array.from({ length: windowDays }, (_, i) => addDaysIso(start, i));

  return (
    <div className="flex gap-2xs overflow-x-auto pb-2xs" role="tablist" aria-label="Pick a day">
      {days.map((iso) => {
        const isSelected = iso === selected;
        return (
          <button
            key={iso}
            type="button"
            role="tab"
            aria-selected={isSelected}
            data-testid="day-tab"
            data-iso={iso}
            onClick={() => onSelect(iso)}
            className={cn(
              "flex min-h-[60px] shrink-0 flex-col items-start gap-3xs rounded-sm border px-sm py-2xs transition duration-150 ease-snap",
              isSelected
                ? "border-accent bg-accent text-[oklch(0.18_0.02_145)]"
                : "border-rule bg-surface text-ink hover:border-rule-strong",
            )}
          >
            <span
              className={cn(
                "label-caps",
                isSelected ? "text-[oklch(0.18_0.02_145)]" : "text-ink-soft",
              )}
            >
              {formatDayHeader(iso)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
