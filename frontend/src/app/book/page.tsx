"use client";

import { useEffect, useState } from "react";

import { CartPanel } from "@/components/calendar/CartPanel";
import { DayPicker } from "@/components/calendar/DayPicker";
import { SlotCell } from "@/components/calendar/SlotCell";
import { Header } from "@/components/ui/Header";
import {
  addDaysIso,
  fetchCalendar,
  formatLocalHour,
  todayIso,
  type CalendarResponse,
  type CalendarSlot,
} from "@/lib/calendar";
import { useCartStore } from "@/lib/cartStore";

const VENUE_ID = 1;
const WINDOW_DAYS = 7;

function slotLabel(slot: CalendarSlot, timezone: string): string {
  const time = formatLocalHour(slot.start_at, timezone);
  const date = new Date(slot.start_at).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: timezone,
  });
  return `${date} · ${time}`;
}

export default function BookPage() {
  const [start] = useState(() => todayIso());
  const [selectedDate, setSelectedDate] = useState(() => todayIso());
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const cartSlots = useCartStore((s) => s.slots);
  const toggle = useCartStore((s) => s.toggle);

  useEffect(() => {
    const end = addDaysIso(start, WINDOW_DAYS - 1);
    let cancelled = false;
    setLoading(true);
    fetchCalendar(VENUE_ID, start, end)
      .then((data) => {
        if (!cancelled) {
          setCalendar(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "unknown error";
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [start]);

  const day = calendar?.days.find((d) => d.date === selectedDate);
  const tz = calendar?.timezone ?? "Asia/Dhaka";
  const cartStarts = new Set(cartSlots.map((s) => s.startAt));

  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-md px-md py-2xl">
        <div className="flex flex-col gap-2xs">
          <p className="label-caps text-brand">Book a slot</p>
          <h1 className="stadium-display text-5xl uppercase text-ink">
            Pick the pitch.
          </h1>
          <p className="text-sm text-ink-soft">
            {calendar
              ? `${calendar.venue_name} · ${calendar.timezone}`
              : "Loading…"}
          </p>
        </div>

        <DayPicker
          start={start}
          selected={selectedDate}
          windowDays={WINDOW_DAYS}
          onSelect={setSelectedDate}
        />

        {error && (
          <p
            role="alert"
            data-testid="calendar-error"
            className="rounded-xs border border-[var(--color-danger)] bg-surface px-sm py-xs text-sm text-[var(--color-danger)]"
          >
            Calendar unavailable — {error}
          </p>
        )}

        {loading && !calendar && (
          <p className="text-sm text-ink-mute">Loading slots…</p>
        )}

        <div className="grid gap-md lg:grid-cols-[3fr_1fr]">
          <div className="flex flex-col gap-md">
            {day?.is_closed && (
              <div
                className="rounded-md border border-rule bg-surface px-md py-lg text-center"
                data-testid="day-closed"
              >
                <p className="stadium-display text-3xl uppercase text-ink">Closed</p>
                <p className="mt-2xs text-sm text-ink-soft">
                  No slots scheduled for this day.
                </p>
              </div>
            )}

            {day && !day.is_closed && (
              <section
                className="grid gap-2xs sm:grid-cols-2 lg:grid-cols-3"
                data-testid="slot-grid"
              >
                {day.slots.map((slot) => {
                  const isSelected = cartStarts.has(slot.start_at);
                  return (
                    <SlotCell
                      key={slot.start_at}
                      slot={slot}
                      timezone={tz}
                      venueId={VENUE_ID}
                      selected={isSelected}
                      onToggle={() =>
                        toggle(VENUE_ID, {
                          startAt: slot.start_at,
                          endAt: slot.end_at,
                          priceBdt: slot.price_bdt,
                          label: slotLabel(slot, tz),
                        })
                      }
                    />
                  );
                })}
              </section>
            )}

            <p className="pt-2xs text-xs text-ink-mute">
              Tap a slot to add it to the cart. Hold reserves slots for 8 minutes
              while you sign in / pay.
            </p>
          </div>

          <div className="lg:sticky lg:top-20 lg:self-start">
            <CartPanel />
          </div>
        </div>
      </main>
    </>
  );
}

