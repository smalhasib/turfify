import { API_BASE_URL } from "@/lib/api";

export type SlotStatus = "available" | "booked" | "blocked" | "past";

export type CalendarSlot = {
  start_at: string; // ISO UTC
  end_at: string;
  status: SlotStatus;
  price_bdt: number;
};

export type CalendarDay = {
  date: string; // YYYY-MM-DD (venue local)
  is_closed: boolean;
  slots: CalendarSlot[];
};

export type CalendarResponse = {
  venue_id: number;
  venue_name: string;
  timezone: string;
  days: CalendarDay[];
};

export async function fetchCalendar(
  venueId: number,
  fromDate: string,
  toDate: string,
): Promise<CalendarResponse> {
  const url = new URL(`${API_BASE_URL}/venues/${venueId}/calendar`);
  url.searchParams.set("from", fromDate);
  url.searchParams.set("to", toDate);

  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Calendar fetch failed: ${res.status} ${body}`);
  }
  return res.json();
}

export function isoDateInTz(d: Date, _tz: string): string {
  // Simple ISO date in local tz; for MVP we read from system locale.
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function todayIso(): string {
  return isoDateInTz(new Date(), "Asia/Dhaka");
}

export function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y!, m! - 1, d!));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

export function formatLocalHour(iso: string, tz = "Asia/Dhaka"): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: tz,
  });
}

export function formatPriceBdt(amount: number): string {
  return `BDT ${amount.toLocaleString("en-BD")}`;
}

export function formatDayHeader(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y!, m! - 1, d!));
  const weekday = dt.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
  const dayNum = dt.toLocaleDateString("en-US", { day: "numeric", timeZone: "UTC" });
  const month = dt
    .toLocaleDateString("en-US", { month: "short", timeZone: "UTC" })
    .toUpperCase();
  return `${weekday.toUpperCase()} · ${dayNum} ${month}`;
}
