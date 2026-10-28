import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type SpaceWorksLogoProps = {
  size?: number;
  withWordmark?: boolean;
  className?: string;
};

// The Tinker Space Inventory tile, the same file the browser uses as its favicon.
function SpaceWorksMark({ size, className, decorative = false }: { size: number; className?: string; decorative?: boolean }) {
  return (
    <img
      // Beside the "Space Works" wordmark the image is decorative, or it is read out twice.
      alt={decorative ? "" : "Space Works"}
      className={className}
      height={size}
      src="/favicon.png"
      width={size}
    />
  );
}

export function SpaceWorksLogo({
  size = 28,
  withWordmark = false,
  className,
}: SpaceWorksLogoProps) {
  if (withWordmark) {
    return (
      <span
        className={[
          "inline-flex min-w-0 max-w-full items-center gap-2",
          className,
        ].filter(Boolean).join(" ")}
      >
        <SpaceWorksMark className="shrink-0" decorative size={size} />
        <span className="min-w-0 break-words font-semibold tracking-wide">Space Works</span>
      </span>
    );
  }

  return <SpaceWorksMark className={className} size={size} />;
}

export function SpaceWorksHomeLink({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      aria-label="Open makerspace listing"
      className={[
        "inline-flex min-w-0 max-w-full text-left transition pointer-coarse:min-h-11 pointer-coarse:items-center hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        className,
      ].filter(Boolean).join(" ")}
      to="/"
    >
      {children}
    </Link>
  );
}

export function SpaceWorksBadge({ className }: { className?: string }) {
  return (
    <SpaceWorksHomeLink
      className={[
        "text-muted",
        className,
      ].filter(Boolean).join(" ")}
    >
      <SpaceWorksLogo size={22} withWordmark />
    </SpaceWorksHomeLink>
  );
}
