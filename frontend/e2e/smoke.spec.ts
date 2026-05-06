import { expect, test } from "@playwright/test";

test.describe("Phase 0 smoke", () => {
  test("home page renders Turfify heading", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Turfify" })).toBeVisible();
    await expect(page.getByTestId("cta-signin")).toBeVisible();
  });

  test("health badge shows backend status", async ({ page }) => {
    await page.goto("/");
    const badge = page.getByTestId("health-status");
    await expect(badge).toBeVisible({ timeout: 10_000 });
    // Either "ok" if backend is up, or "unreachable" — both valid for smoke.
    await expect(badge).toHaveText(/ok|unreachable/i);
  });
});
