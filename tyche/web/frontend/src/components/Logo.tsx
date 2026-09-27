import clsx from "clsx";

/** Tyche's mark: a wheel of fortune (ring, three spokes, hub). Monochrome, follows currentColor. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={clsx("shrink-0", className ?? "h-6 w-6")} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="8.4" stroke="currentColor" strokeWidth="1.9" />
      <path
        d="M12 12V3.9M12 12l-7 4.05M12 12l7 4.05"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
      />
      <circle cx="12" cy="12" r="1.9" fill="currentColor" />
    </svg>
  );
}

/** Round avatar used for Tyche's messages and the empty state. */
export function LogoAvatar({ className, spinning }: { className?: string; spinning?: boolean }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center justify-center rounded-full border border-line/10 bg-main text-fg",
        className ?? "h-8 w-8",
      )}
    >
      <LogoMark className={clsx("h-[62%] w-[62%]", spinning && "animate-[spin_3s_linear_infinite]")} />
    </span>
  );
}
