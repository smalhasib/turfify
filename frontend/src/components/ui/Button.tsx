import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "ghost" | "outline" | "danger";
type Size = "md" | "lg";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
};

const base =
  "inline-flex items-center justify-center gap-2 rounded-sm font-sans font-semibold transition duration-150 ease-snap " +
  "disabled:cursor-not-allowed disabled:opacity-50 select-none whitespace-nowrap " +
  // 44px+ touch target floor
  "min-h-[44px]";

const sizes: Record<Size, string> = {
  md: "px-md py-2xs text-sm",
  lg: "px-lg py-xs text-base",
};

const variants: Record<Variant, string> = {
  // Hype CTA. Sodium-vapor amber. Reserved for booking actions / primary submits.
  primary:
    "bg-accent text-[oklch(0.18_0.02_145)] hover:bg-accent-deep hover:text-[oklch(0.96_0.01_95)] active:translate-y-px",
  // Quiet alternate. Used for navigation, secondary submits.
  ghost:
    "bg-transparent text-ink hover:bg-surface-2 active:translate-y-px",
  // Bordered for cancel / secondary destructive-light actions.
  outline:
    "bg-transparent text-ink border border-rule-strong hover:bg-surface-2 active:translate-y-px",
  // Hard destructive. Phase 9+ refunds, deletes.
  danger:
    "bg-[var(--color-danger)] text-[oklch(0.98_0.01_95)] hover:brightness-110 active:translate-y-px",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, className, disabled, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(base, sizes[size], variants[variant], className)}
      disabled={disabled || loading}
      data-loading={loading ? "true" : undefined}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-r-transparent"
        />
      )}
      {children}
    </button>
  );
});
