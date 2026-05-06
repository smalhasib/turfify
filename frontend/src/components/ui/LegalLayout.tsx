import { type ReactNode } from "react";

import { Header } from "@/components/ui/Header";

type Props = {
  kicker: string;
  title: string;
  updatedAt: string;
  children: ReactNode;
};

export function LegalLayout({ kicker, title, updatedAt, children }: Props) {
  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-md px-md py-2xl">
        <div className="flex flex-col gap-2xs">
          <p className="label-caps text-brand">{kicker}</p>
          <h1 className="stadium-display text-5xl uppercase text-ink">{title}</h1>
          <p className="text-xs text-ink-mute">Last updated: {updatedAt}</p>
        </div>
        <article className="prose-sm flex flex-col gap-sm text-base leading-relaxed text-ink">
          {children}
        </article>
      </main>
    </>
  );
}
