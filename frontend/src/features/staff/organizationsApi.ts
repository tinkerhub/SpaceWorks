import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type OrganizationSummary = {
  id: number;
  slug: string;
  name: string;
  governance_actions: string[];
  granted_actions: string[];
};

export const organizationKeys = {
  all: ["organizations"] as const,
  list: (page: number) => ["organizations", "list", page] as const,
};

/** Organizations the actor can attribute an event to (the event organizer picker). */
export function useOrganizations(page = 1) {
  return useQuery({
    queryKey: organizationKeys.list(page),
    queryFn: () => staffRequest<Page<OrganizationSummary>>(`/admin/organizations/?page=${page}`),
  });
}
