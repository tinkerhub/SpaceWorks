import { useMemo } from "react";

import { Skeleton } from "../../../components/ui";
import { useStaffGet } from "./shared";

type QrPrintPayload = {
  payload: string;
  svg: string;
};

export function QrImage({ qrId, label }: { qrId: number; label: string }) {
  const qr = useStaffGet<QrPrintPayload>(["qr-image", qrId], `/admin/qr/${qrId}/print`);
  const src = useMemo(() => {
    if (!qr.data?.svg) return "";
    return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(qr.data.svg)))}`;
  }, [qr.data?.svg]);

  if (qr.isLoading) {
    return (
      <div role="status" className="relative aspect-square w-full">
        <Skeleton className="absolute inset-0 rounded-md" />
        <span className="sr-only">Loading QR</span>
      </div>
    );
  }

  if (qr.isError || !src) {
    return <div className="grid aspect-square place-items-center rounded-md border border-dashed border-danger-border bg-danger-bg p-2 text-center text-caption text-danger-fg">QR unavailable</div>;
  }

  // The QR stays black on white in both themes so it scans from a screen.
  return <img className="aspect-square w-full rounded-md border border-line bg-white p-2" src={src} alt={`${label} QR`} />;
}
