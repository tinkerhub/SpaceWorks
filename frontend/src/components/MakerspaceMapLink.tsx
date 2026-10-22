import { MapPin } from "lucide-react";

type MakerspaceLocation = {
  location?: string | null;
  map_url?: string | null;
};

type MakerspaceMapLinkProps = {
  makerspace?: MakerspaceLocation | null;
  className?: string;
  locationClassName?: string;
  linkClassName?: string;
};

export function MakerspaceMapLink({
  makerspace,
  className = "",
  locationClassName = "text-body-ui text-ink-muted",
  linkClassName = "inline-flex items-center gap-1 rounded-sm text-label text-accent-ink underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
}: MakerspaceMapLinkProps) {
  const location = makerspace?.location?.trim() ?? "";
  const mapUrl = makerspace?.map_url?.trim() ?? "";

  if (!location && !mapUrl) {
    return null;
  }

  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-0.5 ${className}`}>
      {location ? <span className={locationClassName}>{location}</span> : null}
      {mapUrl ? (
        <a
          className={linkClassName}
          href={mapUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <MapPin aria-hidden="true" className="size-4 shrink-0" />
          Open in Google Maps
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ) : null}
    </div>
  );
}
