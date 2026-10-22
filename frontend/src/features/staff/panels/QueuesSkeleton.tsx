import { SkeletonRows } from "../../../components/ui/Skeleton";

/** Placeholder rows in the same bordered table shape the request list uses. */
export function RequestListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="w-full min-w-0 overflow-x-auto rounded-lg border border-line bg-canvas" aria-hidden="true">
      <table className="w-full">
        <tbody>
          <SkeletonRows rows={rows} cols={5} />
        </tbody>
      </table>
    </div>
  );
}
