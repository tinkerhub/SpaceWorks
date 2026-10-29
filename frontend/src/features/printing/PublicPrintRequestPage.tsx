import { PublicMachineServicePage } from "../machineService/PublicMachineServicePage";

/** Keep existing /print links and private tokens on the shared intake flow. */
export function PublicPrintRequestPage() {
  return <PublicMachineServicePage defaultPrinter />;
}
