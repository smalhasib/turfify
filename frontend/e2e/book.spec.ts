import { expect, test, type Page } from "@playwright/test";

const SAMPLE_RESPONSE = {
  venue_id: 1,
  venue_name: "Turfify Main",
  timezone: "Asia/Dhaka",
  days: [] as unknown[],
};

function buildSampleCalendar(start: string, days: number) {
  const out: typeof SAMPLE_RESPONSE = {
    ...SAMPLE_RESPONSE,
    days: [],
  };
  const [y, m, d] = start.split("-").map(Number);
  for (let i = 0; i < days; i++) {
    const date = new Date(Date.UTC(y!, m! - 1, d! + i));
    const iso = date.toISOString().slice(0, 10);
    const slots: unknown[] = [];
    // 6 slots from 16:00 -> 22:00 Dhaka (10:00 -> 16:00 UTC)
    for (let hr = 16; hr < 22; hr++) {
      const startUtc = new Date(Date.UTC(y!, m! - 1, d! + i, hr - 6));
      const endUtc = new Date(startUtc.getTime() + 60 * 60 * 1000);
      slots.push({
        start_at: startUtc.toISOString(),
        end_at: endUtc.toISOString(),
        status: hr === 17 ? "booked" : hr === 18 ? "blocked" : "available",
        price_bdt: hr >= 18 ? 1500 : 1000,
      });
    }
    out.days.push({ date: iso, is_closed: i === 3, slots: i === 3 ? [] : slots });
  }
  return out;
}

async function stubCalendar(page: Page) {
  await page.route("**/v1/venues/1/calendar*", async (route) => {
    const url = new URL(route.request().url());
    const fromDate = url.searchParams.get("from")!;
    const toDate = url.searchParams.get("to")!;
    const [fy, fm, fd] = fromDate.split("-").map(Number);
    const [ty, tm, td] = toDate.split("-").map(Number);
    const start = Date.UTC(fy!, fm! - 1, fd!);
    const end = Date.UTC(ty!, tm! - 1, td!);
    const days = Math.round((end - start) / 86400000) + 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildSampleCalendar(fromDate, days)),
    });
  });
}

test.describe("Phase 3 booking calendar", () => {
  test.beforeEach(async ({ page }) => {
    await stubCalendar(page);
  });

  test("renders day picker + slot grid for selected day", async ({ page }) => {
    await page.goto("/book");

    await expect(page.getByRole("heading", { name: /pick the pitch/i })).toBeVisible();
    await expect(page.getByTestId("day-tab")).toHaveCount(7);
    await expect(page.getByTestId("slot-grid")).toBeVisible();
    await expect(page.getByTestId("slot-cell")).toHaveCount(6);
  });

  test("each slot shows price + status pill", async ({ page }) => {
    await page.goto("/book");

    const firstSlot = page.getByTestId("slot-cell").first();
    await expect(firstSlot).toContainText("BDT");
    await expect(page.getByTestId("slot-status").first()).toBeVisible();
  });

  test("clicking a different day swaps the slot grid", async ({ page }) => {
    await page.goto("/book");
    const tabs = page.getByTestId("day-tab");
    await expect(tabs).toHaveCount(7);

    // The 4th day (i=3) is mocked as closed → slot grid disappears, closed banner shows.
    await tabs.nth(3).click();
    await expect(page.getByTestId("day-closed")).toBeVisible();
    await expect(page.getByTestId("slot-grid")).not.toBeVisible();
  });

  test("booked + blocked slots are disabled", async ({ page }) => {
    await page.goto("/book");
    const cells = page.getByTestId("slot-cell");
    await expect(cells).toHaveCount(6);
    const booked = cells.filter({ has: page.getByText("BOOKED", { exact: true }) });
    await expect(booked).toBeDisabled();
    const blocked = cells.filter({ has: page.getByText("BLOCKED", { exact: true }) });
    await expect(blocked).toBeDisabled();
  });
});
