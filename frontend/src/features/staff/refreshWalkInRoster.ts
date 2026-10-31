import type { QueryClient } from "@tanstack/react-query";

/** A real canonical option is required; never fill in membership fields from a creation receipt. */
function containsPerson(data: unknown, userId: number): boolean {
  const rows = Array.isArray(data) ? data : data && typeof data === "object" && "results" in data ? data.results : null;
  if (!Array.isArray(rows)) return false;
  const valid = rows.every((row: unknown) => row !== null && typeof row === "object" &&
    "user_id" in row && Number.isSafeInteger(row.user_id) && Number(row.user_id) > 0 &&
    "membership_id" in row && Number.isSafeInteger(row.membership_id) && Number(row.membership_id) > 0 &&
    "display_name" in row && typeof row.display_name === "string" &&
    "username" in row && typeof row.username === "string" &&
    "is_walk_in" in row && typeof row.is_walk_in === "boolean");
  return valid && rows.some((row) => row.user_id === userId);
}

/** Observe only this selection attempt. Retiring it never cancels the shared roster fetch. */
export function refreshWalkInRoster(client: QueryClient, makerId: number, userId: number, current: () => boolean) {
  let resolve!: (found: boolean) => void;
  const result = new Promise<boolean>((done) => { resolve = done; });
  let active = true;
  let retired = false;
  let unsubscribe = () => {};
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const finish = (found = false) => {
    if (!active) return;
    active = false;
    unsubscribe();
    clearTimeout(timeout);
    resolve(found);
  };
  const retire = () => { retired = true; finish(); };
  const filters = { queryKey: ["direct-loan-members", makerId], exact: true };
  const cache = client.getQueryCache();
  const query = cache.find(filters);
  const eligible = () => Boolean(query && cache.find(filters) === query && query.isActive() &&
    !query.isDisabled() && !query.isStatic() && typeof query.options.queryFn === "function" &&
    ["pending", "error", "success"].includes(query.state.status) &&
    ["idle", "fetching", "paused"].includes(query.state.fetchStatus) &&
    Number.isSafeInteger(query.state.dataUpdateCount) && query.state.dataUpdateCount >= 0);
  if (!query || !Number.isSafeInteger(userId) || userId <= 0 || !current() || !eligible()) {
    finish();
    return { result, retire, canSelect: () => false };
  }

  const roster = query;
  const baseline = roster.state.dataUpdateCount;
  let fetching = false;
  let proof: { data: unknown; count: number } | null = null;
  const canSelect = () => {
    const state = roster.state;
    return Boolean(!retired && current() && eligible() && proof && state.status === "success" &&
      state.fetchStatus === "idle" && state.error === null && !state.isInvalidated &&
      state.dataUpdateCount === proof.count && state.data === proof.data && containsPerson(state.data, userId));
  };
  unsubscribe = cache.subscribe((event) => {
    if (!active || event.query !== query) return;
    if (!current() || event.type === "removed" || !eligible() || query.state.fetchStatus === "paused") {
      finish();
      return;
    }
    if (event.type !== "updated") return;
    if (event.action.type === "fetch") {
      fetching = true;
      proof = null;
    } else if (event.action.type === "success") {
      // setQueryData also emits success, but its manual write is not evidence of a read.
      proof = fetching && !event.action.manual && query.state.dataUpdateCount > baseline
        ? { data: event.action.data, count: query.state.dataUpdateCount } : null;
    } else if (event.action.type === "error" || event.action.type === "setState") {
      // Cancellation/reversion and unrecognised manual state replacement cannot authorize selection.
      finish();
    }
  });
  // Bound local observation even if a transport never settles. The shared read can still cache later.
  timeout = setTimeout(finish, 30_000);

  async function read() {
    try {
      // Separate invalidation from fetching so we retain the actual fetch promise, even if paused.
      // invalidateQueries' automatic refetch can drop that promise when it starts paused.
      await client.invalidateQueries({ ...filters, refetchType: "none" }, { throwOnError: true });
      if (!active || !current() || !eligible() || roster.state.fetchStatus === "paused") {
        finish();
        return;
      }
      fetching = roster.state.fetchStatus === "fetching";
      await roster.fetch(undefined, { cancelRefetch: false });
      // A retired/paused attempt still consumes eventual rejection, but can never publish.
      if (!active) return;
      finish(canSelect());
    } catch {
      finish();
    }
  }
  void read();
  return { result, retire, canSelect };
}
