import { useTenantBootstrap } from "./usePublicInventory";

/**
 * How borrower copy names the upstream check-in system. Reads the cached public bootstrap;
 * without a configured name (or before it loads) the copy stays neutral.
 */
export function useCheckinProvider(makerspaceSlug: string) {
  const checkin = useTenantBootstrap(makerspaceSlug).data?.makerspace?.checkin;
  const provider = checkin?.provider?.trim() ?? "";
  return {
    provider,
    purpose: checkin?.purpose?.trim() || "Working on a project",
    // "as it appears in TinkerHub" / "as it appears on the check-in list"
    appearsIn: provider ? `in ${provider}` : "on the check-in list",
    app: provider ? `the ${provider} app` : "your check-in app",
  };
}
