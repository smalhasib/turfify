"use client";

import { getApiClient } from "@/lib/api";

export type PaymentMethod = "online" | "cash";

export type PaymentCollection =
  | "online"
  | "cash"
  | "bkash_manual"
  | "free"
  | "pending_offline"
  | "cash_pending";

export type HoldRequest = {
  venue_id: number;
  slots: { start_at: string }[];
  discount_code?: string | null;
  payment_method?: PaymentMethod;
};

export type HoldResponse = {
  booking_id: number;
  public_id: string;
  payment_method: PaymentMethod;
  hold_token: string | null;
  hold_expires_at: string | null;
  subtotal_bdt: number;
  discount_code: string | null;
  discount_amount_bdt: number;
  total_bdt: number;
  slot_count: number;
};

export type DiscountValidateRequest = {
  code: string;
  subtotal_bdt: number;
  slot_dates: string[];
};

export type DiscountValidateResponse = {
  code: string;
  type: "percent" | "flat";
  amount_off_bdt: number;
  final_total_bdt: number;
};

export async function validateDiscountCode(
  payload: DiscountValidateRequest,
): Promise<DiscountValidateResponse> {
  const { data } = await getApiClient().post<DiscountValidateResponse>(
    "/discount-codes/validate",
    payload,
  );
  return data;
}

export type BookingStatus =
  | "pending_payment"
  | "confirmed"
  | "expired"
  | "failed"
  | "cancelled"
  | "auto_cancelled_no_payment"
  | "payment_received_no_slot"
  | "refund_pending"
  | "refunded"
  | "refund_failed"
  | "completed";

export type BookingSlotOut = {
  slot_start_at: string;
  slot_end_at: string;
  price_bdt: number;
};

export type BookingStatusResponse = {
  booking_id: number;
  public_id: string;
  status: BookingStatus;
  payment_collection: PaymentCollection;
  venue_id: number;
  total_bdt: number;
  subtotal_bdt: number;
  discount_amount_bdt: number;
  admin_adjustment_bdt: number;
  slot_count: number;
  first_slot_at: string;
  last_slot_at: string;
  hold_expires_at: string | null;
  seconds_to_expiry: number | null;
  slots: BookingSlotOut[];
  created_at: string;
};

export async function createHold(payload: HoldRequest): Promise<HoldResponse> {
  const { data } = await getApiClient().post<HoldResponse>("/bookings/hold", payload);
  return data;
}

export async function fetchBookingStatus(id: number): Promise<BookingStatusResponse> {
  const { data } = await getApiClient().get<BookingStatusResponse>(
    `/bookings/${id}/status`,
  );
  return data;
}

export async function cancelHold(id: number): Promise<BookingStatusResponse> {
  const { data } = await getApiClient().post<BookingStatusResponse>(
    `/bookings/${id}/cancel-hold`,
  );
  return data;
}
