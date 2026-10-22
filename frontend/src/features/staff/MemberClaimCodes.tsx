import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  CardHeader,
  Dropdown,
  EmptyState,
  ErrorText,
  Field,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  useToast,
} from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText } from "./panels/shared";

export type ClaimableMember = {
  membership_id: number;
  user_id: number;
  display_name: string;
  username: string;
  is_walk_in: boolean;
};

type ClaimCode = {
  id: number;
  membership_id: number;
  member_display_name: string;
  issued_by_id: number | null;
  issued_at: string;
  expires_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
  status: "issued" | "consumed" | "revoked";
};

type IssuedClaimCode = ClaimCode & { code: string; qr_svg: string };

export function MemberClaimCodes({
  makerspaceId,
  members,
}: {
  makerspaceId: number;
  members: ClaimableMember[];
}) {
  const queryClient = useQueryClient();
  const queryKey = ["member-claim-codes", makerspaceId];
  const [membershipId, setMembershipId] = useState("");
  const [issued, setIssued] = useState<IssuedClaimCode | null>(null);
  const { showToast } = useToast();
  useEffect(() => {
    setMembershipId("");
    setIssued(null);
  }, [makerspaceId]);
  const active = useQuery({
    queryKey,
    queryFn: () =>
      staffRequest<ClaimCode[]>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes`,
      ),
  });
  const issue = useMutation({
    mutationFn: () =>
      staffRequest<IssuedClaimCode>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes`,
        {
          method: "POST",
          body: JSON.stringify({ membership_id: Number(membershipId) }),
        },
      ),
    onSuccess: (claim) => {
      setIssued(claim);
      showToast("Claim code issued", { tone: "success" });
      void queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => showToast(errorText(error, "Couldn't issue a claim code"), { tone: "error" }),
  });
  const revoke = useMutation({
    mutationFn: (claimId: number) =>
      staffRequest<ClaimCode>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes/${claimId}/revoke`,
        { method: "POST" },
      ),
    onSuccess: (claim) => {
      if (issued?.id === claim.id) setIssued(null);
      showToast("Claim code revoked", { tone: "success" });
      void queryClient.invalidateQueries({ queryKey });
    },
    onError: (error) => showToast(errorText(error, "Couldn't revoke the claim code"), { tone: "error" }),
  });
  const walkIns = members.filter((member) => member.is_walk_in);
  const error = issue.error ?? revoke.error;
  const claims = active.data ?? [];

  return (
    <Card as="section">
      <CardHeader
        title="Member claim code"
        description="Issue only while the walk-in is here in person. Hand over the code or QR; never email or text it."
      />
      <div className="grid gap-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <Field label="Walk-in member" hideLabel className="min-w-0 flex-1">
            <Dropdown value={membershipId} onChange={(event) => setMembershipId(event.target.value)}>
              <option value="" disabled>Select an eligible walk-in</option>
              {walkIns.map((member) => (
                <option key={member.membership_id} value={member.membership_id}>
                  {member.display_name || member.username}
                </option>
              ))}
            </Dropdown>
          </Field>
          <Button
            variant="secondary"
            disabled={!membershipId}
            loading={issue.isPending}
            loadingLabel="Issuing…"
            onClick={() => issue.mutate()}
          >
            Issue claim code
          </Button>
        </div>
        {issued ? (
          <div className="grid gap-4 rounded-lg border border-line bg-subtle p-4 md:grid-cols-[1fr_180px]">
            <div>
              <p className="text-label text-ink">Hand this to {issued.member_display_name}</p>
              <p className="mt-2 break-all font-mono text-lg font-semibold text-ink">{issued.code}</p>
              <p className="mt-2 text-caption text-ink-muted">
                Expires {new Date(issued.expires_at).toLocaleString()}. This code will not be shown again after you leave this view.
              </p>
            </div>
            <img
              className="aspect-square w-full rounded-md border border-line bg-white p-2"
              src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(issued.qr_svg)}`}
              alt={`Claim code QR for ${issued.member_display_name}`}
            />
          </div>
        ) : null}
        <ErrorText message={active.error?.message ?? error?.message} />
        {active.isLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : !claims.length ? (
          <EmptyState title="No active claim codes." description="Codes you issue appear here until they're used, revoked or expire." />
        ) : (
          <Table label="Active claim codes">
            <THead><tr><TH>Member</TH><TH>Expires</TH><TH><span className="sr-only">Actions</span></TH></tr></THead>
            <TBody>
              {claims.map((claim) => (
                <TR key={claim.id}>
                  <TD className="font-semibold">{claim.member_display_name}</TD>
                  <TD className="text-ink-secondary">{new Date(claim.expires_at).toLocaleString()}</TD>
                  <TD>
                    <div className="flex justify-end">
                      <Button size="sm" variant="danger-quiet" disabled={revoke.isPending} onClick={() => revoke.mutate(claim.id)}>
                        Revoke
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
    </Card>
  );
}
