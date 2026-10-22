import type { ClaimableMember } from "./MemberClaimCodes";

export type ProductOption = {
  id: number;
  name: string;
  storage_location: string;
  available_quantity: number;
  tracking_mode: string;
  is_public: boolean;
  public_self_checkout_enabled: boolean;
  is_archived: boolean;
};
export type ContainerOption = { id: number; label: string };
export type ContainerResponse = ContainerOption[] | { results: ContainerOption[] };
// Phase 7 D4 replaced the inline shape with ClaimableMember, which the claim-code
// surface also consumes: a member the desk can hand a tool to is the same member the
// desk can issue a claim code for, so one type keeps the two panels honest.
export type DirectLoanMember = ClaimableMember;
export type DirectLoanMemberResponse = DirectLoanMember[] | { results: DirectLoanMember[] };
export type LineDraft = { key: number; productId: string; quantity: string };
export type ScannedPayload = { payload: string; label: string };
export type QrResolveResponse = {
  target:
    | { type: "product"; id: number; name: string }
    | { type: "asset"; id: number; asset_tag: string; product: string; status: string }
    | { type: "box"; id: number; label: string; code: string };
};

export const FIRST_LINE: LineDraft = { key: 1, productId: "", quantity: "1" };
export const DEFAULT_ISSUE_REMARK = "Issued from direct handout.";

/** DRF list endpoints answer with the paginated envelope; some older ones with a bare array. */
export function listResults<T>(data: T[] | { results: T[] } | undefined): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results ?? [];
}

export function labelForTarget(target: QrResolveResponse["target"], fallback: string) {
  if (target.type === "product") return `Item: ${target.name || fallback}`;
  if (target.type === "asset") return `Unit: ${target.product} · ${target.asset_tag} · ${target.status.replace(/_/g, " ")}`;
  return `Container: ${target.label || target.code || fallback}`;
}
