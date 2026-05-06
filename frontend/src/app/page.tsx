import Link from "next/link";

import { HealthBadge } from "@/components/HealthBadge";
import { Header } from "@/components/ui/Header";

export default function HomePage() {
  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-6xl px-md pb-3xl pt-2xl">
        <section className="grid gap-2xl md:grid-cols-[3fr_2fr] md:items-end">
          <div className="flex flex-col gap-md">
            <p className="label-caps text-brand">Evening kickoff · Bangladesh</p>
            <h1 className="stadium-display text-[clamp(3.5rem,11vw,8rem)] uppercase text-ink">
              Book the pitch.
              <br />
              Round up the boys.
            </h1>
            <p className="max-w-[55ch] text-lg text-ink-soft">
              Pick a slot, pay with bKash, show up in studs. No phone calls. No double
              bookings. Built for evening 7-a-side in Dhaka.
            </p>
            <div className="flex flex-wrap items-center gap-xs pt-2xs">
              <Link
                href="/login"
                className="inline-flex min-h-[48px] items-center gap-2 rounded-sm bg-accent px-lg py-xs font-sans text-base font-semibold uppercase tracking-wide text-[oklch(0.18_0.02_145)] transition-transform duration-150 ease-snap hover:bg-accent-deep hover:text-[oklch(0.96_0.01_95)] active:translate-y-px"
                data-testid="cta-signin"
              >
                Find a slot
                <ArrowIcon />
              </Link>
              <span className="text-sm text-ink-mute">
                · 2-tap booking · 8-min hold · refunds before T-24h
              </span>
            </div>
          </div>

          <aside className="flex flex-col gap-sm rounded-md border border-rule bg-surface p-md">
            <p className="label-caps">Tonight, somewhere</p>
            <p className="stadium-display text-5xl uppercase text-ink">
              6:00<span className="text-ink-mute">–</span>10:00 PM
            </p>
            <ul className="flex flex-col gap-2xs text-sm">
              <Stat label="Avg. slot" value="BDT 1,000 / hour" />
              <Stat label="Concurrent bookings" value="GIST-locked" />
              <Stat label="Payment" value="bKash · Cash on arrival" />
            </ul>
            <div className="mt-2xs border-t border-rule pt-2xs">
              <p className="label-caps text-ink-soft">Backend status</p>
              <HealthBadge />
            </div>
          </aside>
        </section>

        <section className="mt-3xl grid gap-md sm:grid-cols-3">
          <Step n="01" title="Pick the slot">
            Calendar shows what&apos;s open tonight, this weekend, fortnight ahead. Tap to hold.
          </Step>
          <Step n="02" title="Pay or pick cash">
            bKash for instant confirmation. Or arrive and pay at the gate — we&apos;ll hold the
            slot until 15 min before kickoff.
          </Step>
          <Step n="03" title="Show up. Play.">
            Receipt downloads as PDF. Send it to the group chat. Game on.
          </Step>
        </section>
      </main>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex items-baseline justify-between gap-sm border-b border-rule/60 pb-2xs last:border-0 last:pb-0">
      <span className="text-ink-mute">{label}</span>
      <span className="font-medium text-ink">{value}</span>
    </li>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <article className="flex flex-col gap-2xs">
      <p className="stadium-display text-4xl text-brand">{n}</p>
      <h3 className="font-sans text-lg font-semibold uppercase tracking-wide text-ink">
        {title}
      </h3>
      <p className="text-sm leading-relaxed text-ink-soft">{children}</p>
    </article>
  );
}

function ArrowIcon() {
  return (
    <svg
      aria-hidden
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 10h12M11 5l5 5-5 5" />
    </svg>
  );
}
