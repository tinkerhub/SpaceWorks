import { useQuery } from "@tanstack/react-query";
import { StructuredApiError } from "../../lib/api";
import { fetchServiceTypes } from "./publicApi";

export const serviceTypesKey = (slug: string) => ["public-service-types", slug] as const;

export function useServiceTypes(slug: string, enabled: boolean) {
  return useQuery({
    queryKey: serviceTypesKey(slug),
    queryFn: () => fetchServiceTypes(slug),
    enabled: Boolean(slug) && enabled,
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
}
