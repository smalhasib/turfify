import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: pushMock }),
}));

const startMock = vi.fn();
const completeMock = vi.fn();
vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return {
    ...actual,
    startPhoneAuth: (...args: unknown[]) => startMock(...args),
    completePhoneAuth: (...args: unknown[]) => completeMock(...args),
  };
});

import LoginPage from "@/app/login/page";

beforeEach(() => {
  pushMock.mockReset();
  startMock.mockReset();
  completeMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LoginPage", () => {
  it("rejects invalid phone format inline", async () => {
    render(<LoginPage />);
    fireEvent.change(screen.getByTestId("phone-input"), { target: { value: "+880170000" } });
    fireEvent.submit(screen.getByTestId("phone-form"));
    await waitFor(() => {
      expect(screen.getByTestId("login-error")).toHaveTextContent("+8801XXXXXXXXX");
    });
    expect(startMock).not.toHaveBeenCalled();
  });

  it("submits phone and progresses to OTP stage", async () => {
    startMock.mockResolvedValue({
      confirm: vi.fn().mockResolvedValue({ user: { getIdToken: () => "fake-token" } }),
    });
    render(<LoginPage />);

    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+8801712345678" },
    });
    fireEvent.submit(screen.getByTestId("phone-form"));

    await waitFor(() => {
      expect(screen.getByTestId("otp-form")).toBeInTheDocument();
    });
    expect(startMock).toHaveBeenCalledWith("+8801712345678", "recaptcha-container");
  });

  it("shows error on bad OTP", async () => {
    const confirmation = {
      confirm: vi.fn().mockRejectedValue(new Error("invalid")),
    };
    startMock.mockResolvedValue(confirmation);
    completeMock.mockRejectedValue(new Error("invalid"));

    render(<LoginPage />);
    fireEvent.change(screen.getByTestId("phone-input"), {
      target: { value: "+8801712345678" },
    });
    fireEvent.submit(screen.getByTestId("phone-form"));
    await waitFor(() => screen.getByTestId("otp-form"));

    fireEvent.change(screen.getByTestId("otp-input"), { target: { value: "999999" } });
    fireEvent.submit(screen.getByTestId("otp-form"));

    await waitFor(() => {
      expect(screen.getByTestId("login-error")).toHaveTextContent(/wrong|expired/i);
    });
  });
});
