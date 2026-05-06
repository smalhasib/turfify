"use client";

import { type ConfirmationResult } from "firebase/auth";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Header } from "@/components/ui/Header";
import { Input } from "@/components/ui/Input";
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
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-md flex-col gap-md px-md py-2xl">
        <div className="flex flex-col gap-2xs">
          <p className="label-caps text-brand">Sign in</p>
          <h1 className="stadium-display text-5xl uppercase text-ink">
            {stage === "phone" ? "Phone first." : "Six digits."}
          </h1>
          <p className="text-sm text-ink-soft">
            {stage === "phone"
              ? "We text you a one-time code. No passwords."
              : `Code sent to ${phone}. It expires in a few minutes.`}
          </p>
        </div>

        {stage === "phone" && (
          <form onSubmit={onSubmitPhone} className="flex flex-col gap-md" data-testid="phone-form">
            <Field label="Bangladesh mobile" htmlFor="phone-input" hint="+8801XXXXXXXXX">
              <Input
                id="phone-input"
                type="tel"
                inputMode="tel"
                name="phone"
                data-testid="phone-input"
                value={phone}
                onChange={(e) => setPhone(e.target.value.trim())}
                placeholder="+8801712345678"
                autoComplete="tel"
                required
                invalid={Boolean(error) && stage === "phone"}
              />
            </Field>
            <Button type="submit" data-testid="send-code" loading={busy} size="lg">
              {busy ? "Sending" : "Send code"}
            </Button>
          </form>
        )}

        {stage === "otp" && (
          <form onSubmit={onSubmitCode} className="flex flex-col gap-md" data-testid="otp-form">
            <Field label="One-time code" htmlFor="otp-input">
              <Input
                id="otp-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                minLength={6}
                data-testid="otp-input"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
                className="stadium-display tracking-[0.4em] text-2xl text-center"
                required
                invalid={Boolean(error) && stage === "otp"}
              />
            </Field>
            <Button
              type="submit"
              data-testid="verify-code"
              loading={busy}
              disabled={code.length < 6}
              size="lg"
            >
              {busy ? "Verifying" : "Verify"}
            </Button>
            <button
              type="button"
              onClick={() => {
                setStage("phone");
                setCode("");
                setConfirmation(null);
                setError(null);
              }}
              className="self-center text-sm text-ink-soft underline-offset-4 hover:text-ink hover:underline"
            >
              Use a different number
            </button>
          </form>
        )}

        {error && (
          <p
            role="alert"
            data-testid="login-error"
            className="rounded-xs border border-[var(--color-danger)] bg-surface px-sm py-xs text-sm text-[var(--color-danger)]"
          >
            {error}
          </p>
        )}

        <div id="recaptcha-container" className="mt-md" />
      </main>
    </>
  );
}
