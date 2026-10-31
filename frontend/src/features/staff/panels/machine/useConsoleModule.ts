import { moduleEnabled } from "../../../../lib/modules";
import { useStaffMakerspaces } from "../../useStaffMakerspaces";

/**
 * Whether a module is on for this makerspace, for machine surfaces that sit beside an
 * optional module (`payments` for pricing and charge chips, `bookings` for "book a slot").
 *
 * With `payments` off no machine-service charge is ever raised (`offline_payments` refuses
 * new charges), so pricing, "Enable payment" and "Payment free" describe something that
 * cannot happen there and must not show. Reads the console's own makerspace list -- the
 * same key and path `useStaffSession` uses, so it is answered from that cache -- rather
 * than threading one more flag through every machine surface. Fails closed while loading.
 */
export function useConsoleModule(makerspaceId: number, key: string): boolean {
  const makerspaces = useStaffMakerspaces();
  if (makerspaces.isPending || makerspaces.isError) return false;
  const list = Array.isArray(makerspaces.data) ? makerspaces.data : [];
  return moduleEnabled(list.find((space) => space.id === makerspaceId)?.enabled_modules, key);
}
