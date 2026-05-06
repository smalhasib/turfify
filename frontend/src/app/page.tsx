import { HealthBadge } from "@/components/HealthBadge";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-brand-700">Turfify</h1>
        <p className="mt-3 text-neutral-600">Turf Management & Booking Platform</p>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-6 py-4">
        <p className="text-sm text-neutral-500">Backend status</p>
        <HealthBadge />
      </div>

      <p className="text-xs text-neutral-400">Phase 0 — Bootstrap</p>
    </main>
  );
}
