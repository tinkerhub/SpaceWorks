import { useQuery } from "@tanstack/react-query";

import { getSessionGeneration, staffRequest } from "../../lib/api";
import type { Makerspace } from "./panels/shared";

export const staffMakerspacesKey = (generation: number) => ["staff", "makerspaces", generation] as const;

/** Both the chooser and machine module gates read only this auth session's list. */
export function useStaffMakerspaces(enabled = true) {
  const generation = getSessionGeneration();
  return useQuery({
    queryKey: staffMakerspacesKey(generation),
    queryFn: async ({ signal }) => {
      const spaces = await staffRequest<Makerspace[]>("/admin/makerspaces", { signal });
      // Keep the API request epoch guard; also fence cache publication after cancellation
      // or a new login, including transports that finish despite an aborted signal.
      if (signal.aborted || generation !== getSessionGeneration()) {
        throw new Error("Makerspace access changed. Reload the allowed list.");
      }
      return spaces;
    },
    enabled,
  });
}
