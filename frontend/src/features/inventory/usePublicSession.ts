import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

import { getAccessToken, getSessionGeneration, refreshAccessToken, getSessionRevision, subscribeSession } from "../../lib/api";

/**
 * Whether a member is signed in on a public page. A signed-in member who RELOADED holds no
 * in-memory access token -- it lives behind the refresh cookie -- so the page has to exchange
 * it before deciding the caller is anonymous.
 */
export function usePublicSession(makerspaceSlug: string, enabled = true) {
  useSyncExternalStore(subscribeSession, getSessionRevision, getSessionRevision);
  const generation = getSessionGeneration();
  const probe = useQuery({
    queryKey: ["public-request-session", makerspaceSlug, generation],
    queryFn: async ({ signal }) => {
      if (signal.aborted || generation !== getSessionGeneration()) return false;
      const authenticated = getAccessToken() ? true : await refreshAccessToken();
      return !signal.aborted && generation === getSessionGeneration() &&
        authenticated && Boolean(getAccessToken());
    },
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  // The token check covers a sign-in made elsewhere in this SPA after the probe settled.
  const authenticated = generation === getSessionGeneration() && Boolean(getAccessToken());
  return { authenticated, settled: probe.isFetched, signedOut: probe.isFetched && !authenticated };
}
