import { cn } from "@/lib/cn";
import { formatLocalHour, formatPriceBdt, type CalendarSlot } from "@/lib/calendar";

type Props = {
  slot: CalendarSlot;
  timezone: string;
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

export function SlotCell({ slot, timezone }: Props) {
  const interactive = slot.status === "available";

  return (
    <button
      type="button"
      disabled={!interactive}
      data-status={slot.status}
      data-testid="slot-cell"
      className={cn(
        "flex min-h-[88px] flex-col justify-between rounded-sm border border-rule px-sm py-xs text-left transition duration-150 ease-snap",
        statusBg[slot.status],
        interactive && "cursor-pointer hover:border-accent",
        !interactive && "cursor-not-allowed",
      )}
    >
      <div className="flex items-center justify-between gap-2xs">
        <span className={cn("stadium-display text-2xl uppercase tracking-tight", statusInk[slot.status])}>
          {formatLocalHour(slot.start_at, timezone)}
        </span>
        <span className="label-caps" data-testid="slot-status">
          {statusLabel[slot.status]}
        </span>
      </div>
      <span className={cn("text-sm font-medium", statusInk[slot.status])}>
        {formatPriceBdt(slot.price_bdt)}
      </span>
    </button>
  );
}
