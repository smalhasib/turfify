import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

type FieldProps = {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
};

export function Field({ label, htmlFor, hint, error, children, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-2xs", className)}>
      <label htmlFor={htmlFor} className="label-caps text-ink-soft">
        {label}
      </label>
      {children}
      {error ? (
        <p
          role="alert"
          className="text-sm text-[var(--color-danger)]"
          data-testid={`${htmlFor}-error`}
        >
          {error}
        </p>
      ) : hint ? (
        <p className="text-sm text-ink-mute">{hint}</p>
      ) : null}
    </div>
  );
}
