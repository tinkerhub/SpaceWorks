type MakerspaceBrandProps = {
  name: string;
  logoUrl?: string | null;
  /** Visual size of the mark. */
  size?: "sm" | "md" | "lg" | "xl";
  /** Hide the text name beside the logo (logo-only lockup). */
  hideName?: boolean;
  className?: string;
};

const LOGO_SIZE: Record<NonNullable<MakerspaceBrandProps["size"]>, string> = {
  sm: "h-8 w-8",
  md: "h-10 w-10",
  lg: "h-14 w-14",
  xl: "h-16 w-16",
};

const NAME_SIZE: Record<NonNullable<MakerspaceBrandProps["size"]>, string> = {
  sm: "text-base font-bold",
  md: "text-xl font-extrabold tracking-[-0.01em]",
  lg: "text-[28px] font-extrabold tracking-[-0.02em] sm:text-[32px]",
  xl: "text-[30px] font-extrabold tracking-[-0.02em] sm:text-[38px]",
};

/**
 * Renders a makerspace's brand: its uploaded logo when present, otherwise the
 * makerspace NAME as a styled display-face wordmark (the design-system fallback,
 * so every makerspace page is always branded even with no logo on file).
 */
export function MakerspaceBrand({
  name,
  logoUrl,
  size = "md",
  hideName = false,
  className = "",
}: MakerspaceBrandProps) {
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center gap-3 ${className}`}>
      {logoUrl ? (
        <img
          src={logoUrl}
          alt={`${name} logo`}
          className={`${LOGO_SIZE[size]} shrink-0 rounded-lg border border-line bg-canvas object-contain`}
        />
      ) : null}
      {!hideName || !logoUrl ? (
        <span
          className={`min-w-0 font-display leading-tight text-ink [overflow-wrap:anywhere] ${NAME_SIZE[size]}`}
        >
          {name}
        </span>
      ) : null}
    </span>
  );
}
