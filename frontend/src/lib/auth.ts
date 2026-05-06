"use client";

import {
  RecaptchaVerifier,
  signInWithPhoneNumber,
  type ConfirmationResult,
} from "firebase/auth";

import { getApiClient, type TokenPair } from "@/lib/api";
import { type AuthUser, useAuthStore } from "@/lib/authStore";
import { getFirebaseAuth } from "@/lib/firebase";

const BD_PHONE_PATTERN = /^\+8801[3-9]\d{8}$/;

export class AuthFlowError extends Error {}

export function validateBdPhone(phone: string): boolean {
  return BD_PHONE_PATTERN.test(phone);
}

let _recaptcha: RecaptchaVerifier | null = null;

export function ensureRecaptcha(containerId: string): RecaptchaVerifier {
  if (_recaptcha) return _recaptcha;
  _recaptcha = new RecaptchaVerifier(getFirebaseAuth(), containerId, {
    size: "invisible",
  });
  return _recaptcha;
}

export function resetRecaptcha(): void {
  if (_recaptcha) {
    _recaptcha.clear();
    _recaptcha = null;
  }
}

type FirebaseTestHooks = {
  startPhoneAuth?: (phone: string, containerId: string) => Promise<ConfirmationResult>;
};

export async function startPhoneAuth(
  phone: string,
  recaptchaContainerId: string,
): Promise<ConfirmationResult> {
  if (!validateBdPhone(phone)) {
    throw new AuthFlowError("Phone must be a Bangladesh mobile in +8801XXXXXXXXX format");
  }

  // E2E test backdoor: Playwright stubs the Firebase confirmation chain via
  // `window.__FIREBASE_TEST_HOOKS__` so reCAPTCHA + real OTP can be skipped.
  // No-op outside test runs because the window flag is never set.
  if (typeof window !== "undefined") {
    const hooks = (window as unknown as { __FIREBASE_TEST_HOOKS__?: FirebaseTestHooks })
      .__FIREBASE_TEST_HOOKS__;
    if (hooks?.startPhoneAuth) {
      return hooks.startPhoneAuth(phone, recaptchaContainerId);
    }
  }

  const verifier = ensureRecaptcha(recaptchaContainerId);
  return signInWithPhoneNumber(getFirebaseAuth(), phone, verifier);
}

export async function completePhoneAuth(
  confirmation: ConfirmationResult,
  code: string,
): Promise<AuthUser> {
  const credential = await confirmation.confirm(code);
  const idToken = await credential.user.getIdToken();

  const client = getApiClient();
  const { data } = await client.post<TokenPair>("/auth/firebase", { id_token: idToken });
  useAuthStore.getState().setTokens(data.access_token, data.refresh_token);

  const me = await client.get<AuthUser>("/me");
  useAuthStore.getState().setUser(me.data);
  return me.data;
}

export async function logout(): Promise<void> {
  const refresh = useAuthStore.getState().refreshToken;
  if (refresh) {
    try {
      await getApiClient().post("/auth/logout", { refresh_token: refresh });
    } catch {
      // best-effort; revoke happens regardless
    }
  }
  useAuthStore.getState().clear();
  resetRecaptcha();
  try {
    await getFirebaseAuth().signOut();
  } catch {
    // ignore
  }
}
