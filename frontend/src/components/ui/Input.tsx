import { type InputHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "block w-full rounded-xs border bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-mute",
        "transition-colors duration-150 ease-snap min-h-[44px]",
        "border-rule hover:border-rule-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-deep",
        invalid && "border-[var(--color-danger)] focus:border-[var(--color-danger)] focus:ring-[var(--color-danger)]",
        className,
      )}
      {...rest}
    />
  );
});
