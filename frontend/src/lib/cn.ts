/**
 * Concatenate truthy class names. Tiny replacement for clsx — we don't need
 * the full library and avoid the dep.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
