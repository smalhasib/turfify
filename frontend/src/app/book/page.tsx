"use client";

import { useEffect, useState } from "react";

import { DayPicker } from "@/components/calendar/DayPicker";
import { SlotCell } from "@/components/calendar/SlotCell";
import { Header } from "@/components/ui/Header";
import {
  addDaysIso,
  fetchCalendar,
  todayIso,
  type CalendarResponse,
} from "@/lib/calendar";

const VENUE_ID = 1; // single-venue MVP
const WINDOW_DAYS = 7;

export default function BookPage() {
  const [start] = useState(() => todayIso());
  const [selectedDate, setSelectedDate] = useState(() => todayIso());
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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
            className="grid gap-2xs sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
            data-testid="slot-grid"
          >
            {day.slots.map((slot) => (
              <SlotCell
                key={slot.start_at}
                slot={slot}
                timezone={calendar?.timezone ?? "Asia/Dhaka"}
              />
            ))}
          </section>
        )}

        <p className="pt-md text-xs text-ink-mute">
          Tap a slot to add it to the cart. Locks open in Phase 4.
        </p>
      </main>
    </>
  );
}
