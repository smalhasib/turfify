import { expect, test } from "@playwright/test";

test.describe("Phase 11 legal + error pages", () => {
  test("Privacy page renders", async ({ page }) => {
    await page.goto("/privacy");
    await expect(
      page.getByRole("heading", { name: /privacy policy/i }),
    ).toBeVisible();
    await expect(page.getByText(/firebase authentication/i)).toBeVisible();
  });

  test("Terms page renders", async ({ page }) => {
    await page.goto("/terms");
    await expect(
      page.getByRole("heading", { name: /terms of service/i }),
    ).toBeVisible();
    await expect(page.getByText(/cancellation/i).first()).toBeVisible();
  });

  test("Refund policy renders", async ({ page }) => {
    await page.goto("/refund-policy");
    await expect(
      page.getByRole("heading", { name: /refund policy/i }),
    ).toBeVisible();
    await expect(page.getByText(/100% refund/i).first()).toBeVisible();
  });

  test("404 page renders for unknown route", async ({ page }) => {
    await page.goto("/this-route-does-not-exist");
    await expect(page.getByText("Off the pitch.")).toBeVisible();
  });
});
