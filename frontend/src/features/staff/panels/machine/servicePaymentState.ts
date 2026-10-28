import type { MachineServiceRequest } from "../../../../generated/api";
import { formatMoney } from "../../paymentsApi";

type ServicePaymentFields = Pick<
  MachineServiceRequest,
  "payment" | "payment_amount" | "payment_status"
>;

export function paymentState(request: ServicePaymentFields) {
  if (request.payment) {
    const { amount, currency, status } = request.payment;
    const priced = ` ${formatMoney(amount, currency)}`;
    if (status === "pending") return `owed${priced}`;
    if (status === "paid_online" || status === "paid_offline") {
      return `paid${priced}`;
    }
    if (status === "waived") return `waived${priced}`;
    if (status === "canceled") return `canceled${priced}`;
    return `unknown${priced}`;
  }

  if (request.payment_status === "none") return "free";
  const amount = request.payment_amount ? ` ${request.payment_amount}` : "";
  return request.payment_status === "pending" ? `owed${amount}` : `paid${amount}`;
}
