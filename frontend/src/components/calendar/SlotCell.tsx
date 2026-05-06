import { cn } from "@/lib/cn";
import { formatLocalHour, formatPriceBdt, type CalendarSlot } from "@/lib/calendar";

type Props = {
  slot: CalendarSlot;
  timezone: string;
  venueId: number;
  selected: boolean;
  onToggle: () => void;
};

const statusLabel: Record<CalendarSlot["status"], string> = {
  available: "OPEN",
  booked: "BOOKED",
  blocked: "BLOCKED",
  past: "CLOSED",
};

const statusBg: Record<CalendarSlot["status"], string> = {
  available: "bg-surface hover:bg-surface-2",
  booked: "bg-surface-2 opacity-60",
  blocked: "bg-surface-2 opacity-60",
  past: "bg-bg opacity-40",
};

const statusInk: Record<CalendarSlot["status"], string> = {
  available: "text-ink",
  booked: "text-ink-mute line-through",
  blocked: "text-ink-mute",
  past: "text-ink-mute",
};

export function SlotCell({ slot, timezone, venueId: _venueId, selected, onToggle }: Props) {
  const interactive = slot.status === "available";

  return (
    <button
      type="button"
      disabled={!interactive}
      onClick={interactive ? onToggle : undefined}
      data-status={slot.status}
      data-selected={selected ? "true" : undefined}
      data-testid="slot-cell"
      aria-pressed={interactive ? selected : undefined}
      className={cn(
        "flex min-h-[88px] flex-col justify-between rounded-sm border px-sm py-xs text-left transition duration-150 ease-snap",
        selected
          ? "border-accent bg-accent text-[oklch(0.18_0.02_145)]"
          : "border-rule",
        !selected && statusBg[slot.status],
        interactive && !selected && "cursor-pointer hover:border-accent",
        !interactive && "cursor-not-allowed",
      )}
    >
      <div className="flex items-center justify-between gap-2xs">
        <span
          className={cn(
            "stadium-display text-2xl uppercase tracking-tight",
            !selected && statusInk[slot.status],
          )}
        >
          {formatLocalHour(slot.start_at, timezone)}
        </span>
        <span
          className={cn(
            "label-caps",
            selected && "text-[oklch(0.18_0.02_145)]",
          )}
          data-testid="slot-status"
        >
          {selected ? "PICKED" : statusLabel[slot.status]}
        </span>
      </div>
      <span
        className={cn("text-sm font-medium", !selected && statusInk[slot.status])}
      >
        {formatPriceBdt(slot.price_bdt)}
      </span>
    </button>
  );
}
