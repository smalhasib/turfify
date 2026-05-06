"use client";

import { type ConfirmationResult } from "firebase/auth";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import {
  AuthFlowError,
  completePhoneAuth,
  startPhoneAuth,
  validateBdPhone,
} from "@/lib/auth";

type Stage = "phone" | "otp";

export default function LoginPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("phone");
  const [phone, setPhone] = useState("+8801");
  const [code, setCode] = useState("");
  const [confirmation, setConfirmation] = useState<ConfirmationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmitPhone(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!validateBdPhone(phone)) {
      setError("Phone must be +8801XXXXXXXXX");
      return;
    }

    setBusy(true);
    try {
      const conf = await startPhoneAuth(phone, "recaptcha-container");
      setConfirmation(conf);
      setStage("otp");
    } catch (err) {
      setError(err instanceof AuthFlowError ? err.message : "Could not send code");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!confirmation) return;

    setBusy(true);
    try {
      await completePhoneAuth(confirmation, code);
      router.push("/me");
    } catch {
      setError("Wrong or expired code");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12">
      <h1 className="text-3xl font-bold tracking-tight text-brand-700">Sign in</h1>
      <p className="mt-2 text-sm text-neutral-600">
        Use your Bangladesh mobile number to receive a one-time code.
      </p>

      {stage === "phone" && (
        <form onSubmit={onSubmitPhone} className="mt-8 space-y-4" data-testid="phone-form">
          <label className="block text-sm font-medium text-neutral-700">
            Phone number
            <input
              type="tel"
              inputMode="tel"
              name="phone"
              data-testid="phone-input"
              className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2 outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              value={phone}
              onChange={(e) => setPhone(e.target.value.trim())}
              placeholder="+8801XXXXXXXXX"
              required
            />
          </label>

          <button
            type="submit"
            data-testid="send-code"
            disabled={busy}
            className="w-full rounded bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send code"}
          </button>
        </form>
      )}

      {stage === "otp" && (
        <form onSubmit={onSubmitCode} className="mt-8 space-y-4" data-testid="otp-form">
          <p className="text-sm text-neutral-600">
            Enter the 6-digit code sent to <span className="font-medium">{phone}</span>
          </p>
          <label className="block text-sm font-medium text-neutral-700">
            One-time code
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              minLength={6}
              data-testid="otp-input"
              className="mt-1 block w-full rounded border border-neutral-300 px-3 py-2 tracking-widest outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              required
            />
          </label>
          <button
            type="submit"
            data-testid="verify-code"
            disabled={busy || code.length < 6}
            className="w-full rounded bg-brand-600 px-4 py-2 font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Verifying…" : "Verify"}
          </button>
          <button
            type="button"
            onClick={() => {
              setStage("phone");
              setCode("");
              setConfirmation(null);
            }}
            className="block w-full text-center text-sm text-neutral-500 hover:text-neutral-700"
          >
            Use a different number
          </button>
        </form>
      )}

      {error && (
        <p
          role="alert"
          data-testid="login-error"
          className="mt-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}

      <div id="recaptcha-container" className="mt-6" />
    </main>
  );
}
