"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Header } from "@/components/ui/Header";
import { useAuthHydrated, useAuthStore } from "@/lib/authStore";
import {
  cancelHold,
  fetchBookingStatus,
  type BookingStatus,
  type BookingStatusResponse,
} from "@/lib/bookings";
import { formatLocalHour, formatPriceBdt } from "@/lib/calendar";

const STATUS_COPY: Record<BookingStatus, { label: string; tone: "live" | "ok" | "ended" }> = {
  pending_payment: { label: "Hold active", tone: "live" },
  confirmed: { label: "Confirmed", tone: "ok" },
  expired: { label: "Hold expired", tone: "ended" },
  failed: { label: "Payment failed", tone: "ended" },
  cancelled: { label: "Cancelled", tone: "ended" },
  auto_cancelled_no_payment: { label: "Cancelled — no-show", tone: "ended" },
  payment_received_no_slot: { label: "Refund pending", tone: "ended" },
  refund_pending: { label: "Refund pending", tone: "ended" },
  refunded: { label: "Refunded", tone: "ended" },
  refund_failed: { label: "Refund failed", tone: "ended" },
  completed: { label: "Played", tone: "ok" },
};

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function BookingStatusPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const hydrated = useAuthHydrated();
  const accessToken = useAuthStore((s) => s.accessToken);

  const [booking, setBooking] = useState<BookingStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [seconds, setSeconds] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (Number.isNaN(id)) return;
    try {
      const data = await fetchBookingStatus(id);
      setBooking(data);
      setSeconds(data.seconds_to_expiry);
      setError(null);
    } catch (err: unknown) {
      type ErrLike = { response?: { status?: number; data?: { detail?: string } } };
      const e = err as ErrLike;
      const status = e?.response?.status;
      if (status === 401) {
        router.replace("/login");
        return;
      }
      const detail = e?.response?.data?.detail ?? "Could not load booking";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    refresh();
  }, [hydrated, accessToken, refresh, router]);

  // Local countdown tick.
  useEffect(() => {
    if (booking?.status !== "pending_payment" || seconds === null) return;
    if (seconds <= 0) return;
    const t = setInterval(() => setSeconds((s) => (s !== null && s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [booking?.status, seconds]);

  // Re-pull from server when countdown hits zero so status flips to expired.
  useEffect(() => {
    if (seconds === 0 && booking?.status === "pending_payment") {
      refresh();
    }
  }, [seconds, booking?.status, refresh]);

  async function onCancel() {
    setBusy(true);
    try {
      const updated = await cancelHold(id);
      setBooking(updated);
      setSeconds(updated.seconds_to_expiry);
    } catch {
      // ignore — surface stale state
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <>
        <Header />
        <main className="mx-auto max-w-2xl p-2xl text-sm text-ink-mute">
          Loading booking…
        </main>
      </>
    );
  }
  if (error || !booking) {
    return (
      <>
        <Header />
        <main className="mx-auto max-w-2xl p-2xl text-sm text-[var(--color-danger)]">
          {error ?? "Booking not found"}
        </main>
      </>
    );
  }

  const copy = STATUS_COPY[booking.status];
  const isPending = booking.status === "pending_payment";
  const isCashPending =
    booking.status === "confirmed" &&
    booking.payment_collection === "cash_pending";

  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-md px-md py-2xl">
        <div className="flex flex-col gap-2xs">
          <p className="label-caps text-brand">Booking</p>
          <h1
            className="stadium-display text-5xl uppercase text-ink"
            data-testid="booking-public-id"
          >
            {booking.public_id}
          </h1>
          <p
            className="text-sm font-semibold uppercase tracking-wide"
            data-testid="booking-status"
            data-status={booking.status}
          >
            <span
              className={
                copy.tone === "live"
                  ? "text-accent-deep"
                  : copy.tone === "ok"
                    ? "text-success"
                    : "text-ink-mute"
              }
            >
              {copy.label}
            </span>
          </p>
        </div>

        {isPending && seconds !== null && (
          <div
            className="flex flex-col gap-2xs rounded-md border border-accent bg-surface px-md py-sm"
            data-testid="hold-countdown"
          >
            <p className="label-caps text-accent-deep">Hold expires in</p>
            <p className="stadium-display text-6xl uppercase text-ink">
              {formatCountdown(seconds)}
            </p>
            <p className="text-xs text-ink-soft">
              Online payment ships with bKash. For now, the hold releases when
              cancelled.
            </p>
          </div>
        )}

        {isCashPending && (
          <div
            className="flex flex-col gap-2xs rounded-md border border-accent bg-surface px-md py-sm"
            data-testid="cash-awaiting"
          >
            <p className="label-caps text-accent-deep">Awaiting payment</p>
            <p className="stadium-display text-3xl uppercase text-ink">
              Pay at the gate
            </p>
            <p className="text-xs text-ink-soft">
              Bring your booking ID. Staff confirms cash and you&apos;re on the
              pitch. Slot auto-cancels if cash isn&apos;t collected before
              kickoff.
            </p>
          </div>
        )}

        <section className="flex flex-col gap-2xs rounded-md border border-rule bg-surface p-md">
          <p className="label-caps text-ink-soft">Slots</p>
          <ul className="flex flex-col gap-2xs" data-testid="booking-slots">
            {booking.slots.map((slot) => (
              <li
                key={slot.slot_start_at}
                className="flex items-baseline justify-between border-b border-rule/60 pb-2xs last:border-0 last:pb-0"
              >
                <span className="text-sm text-ink">
                  {new Date(slot.slot_start_at).toLocaleDateString("en-US", {
                    weekday: "short",
                    month: "short",
                    day: "numeric",
                  })}{" "}
                  · {formatLocalHour(slot.slot_start_at)}
                </span>
                <span className="text-sm font-medium text-ink">
                  {formatPriceBdt(slot.price_bdt)}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex flex-col gap-3xs border-t border-rule pt-2xs">
            <div className="flex items-baseline justify-between text-sm">
              <span className="text-ink-soft">Subtotal</span>
              <span className="font-medium text-ink">
                {formatPriceBdt(booking.subtotal_bdt)}
              </span>
            </div>
            {booking.discount_amount_bdt > 0 && (
              <div
                className="flex items-baseline justify-between text-sm"
                data-testid="booking-discount-line"
              >
                <span className="text-ink-soft">Discount</span>
                <span className="font-medium text-success">
                  − {formatPriceBdt(booking.discount_amount_bdt)}
                </span>
              </div>
            )}
            <div className="flex items-baseline justify-between">
              <span className="label-caps text-ink-soft">Total</span>
              <span
                className="stadium-display text-3xl uppercase text-ink"
                data-testid="booking-total"
              >
                {formatPriceBdt(booking.total_bdt)}
              </span>
            </div>
          </div>
        </section>

        <div className="flex flex-wrap gap-sm">
          {isPending && (
            <Button
              variant="outline"
              onClick={onCancel}
              loading={busy}
              data-testid="cancel-hold"
            >
              Cancel hold
            </Button>
          )}
          <Button variant="ghost" onClick={() => router.push("/book")}>
            Back to calendar
          </Button>
        </div>
      </main>
    </>
  );
}
