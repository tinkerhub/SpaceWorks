import { useQuery } from "@tanstack/react-query";

import { getAccessToken, refreshAccessToken } from "../../lib/api";

/**
 * Whether a member is signed in on a public page. A signed-in member who RELOADED holds no
 * in-memory access token -- it lives behind the refresh cookie -- so the page has to exchange
 * it before deciding the caller is anonymous.
 */
export function usePublicSession(makerspaceSlug: string, enabled = true) {
  const probe = useQuery({
    queryKey: ["public-request-session", makerspaceSlug],
    queryFn: async () => (getAccessToken() ? true : refreshAccessToken()),
    enabled,
    staleTime: Infinity,
    retry: false,
  });
  // The token check covers a sign-in made elsewhere in this SPA after the probe settled.
  const authenticated = probe.data === true || Boolean(getAccessToken());
  return { authenticated, settled: probe.isFetched, signedOut: probe.isFetched && !authenticated };
}
