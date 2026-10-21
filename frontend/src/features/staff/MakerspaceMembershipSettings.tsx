import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Dropdown, Field, Input, SettingsRow, StatusChip, useToast } from "../../components/ui";
import type { Makerspace as MakerspaceContract, MembershipPolicyEnum } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

export function MakerspaceMembershipSettings({ makerspace, settings, loading }: {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const membershipPolicy = settings?.membership_policy ?? makerspace.membership_policy ?? "request";
  const referralsEnabled = settings?.referrals_enabled ?? makerspace.referrals_enabled ?? false;
  const [duesAmount, setDuesAmount] = useState(
    settings?.membership_dues_amount ?? makerspace.membership_dues_amount ?? "0.00",
  );
  useEffect(() => {
    setDuesAmount(settings?.membership_dues_amount ?? makerspace.membership_dues_amount ?? "0.00");
  }, [settings?.membership_dues_amount, makerspace.membership_dues_amount]);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });
  const updateMembershipPolicy = useMutation({
    mutationFn: (next: MembershipPolicyEnum) => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ membership_policy: next }),
    }),
    onSuccess: () => { refresh(); showToast("Joining policy saved", { tone: "success" }); },
    onError: failed("Couldn't save the joining policy"),
  });
  const updateReferrals = useMutation({
    mutationFn: (next: boolean) => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ referrals_enabled: next }),
    }),
    onSuccess: (_data, next) => { refresh(); showToast(next ? "Referrals are on" : "Referrals are off", { tone: "success" }); },
    onError: failed("Couldn't change referrals"),
  });
  const updateDues = useMutation({
    mutationFn: () => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ membership_dues_amount: duesAmount }),
    }),
    onSuccess: () => { refresh(); showToast("Dues saved", { tone: "success" }); },
    onError: failed("Couldn't save the dues"),
  });

  return (
    <Card as="section">
      <CardHeader
        title="Membership"
        description="How people join, whether members can refer others, and what joining costs."
        action={<StatusChip tone={membershipPolicy === "invite_only" ? "neutral" : "success"} size="sm">{membershipPolicyLabel(membershipPolicy)}</StatusChip>}
      />
      <SettingsRow
        title="Membership joining"
        description="Choose whether people join immediately, request approval, or need an invitation. This only controls self-join; manager invitations remain available."
      >
        <Field label="Membership joining policy" hideLabel error={updateMembershipPolicy.error?.message} className="max-w-xs">
          <Dropdown
            value={membershipPolicy}
            disabled={loading || updateMembershipPolicy.isPending}
            onChange={(event) => updateMembershipPolicy.mutate(event.target.value as MembershipPolicyEnum)}
          >
            <option value="open">Join instantly</option>
            <option value="request">Request approval</option>
            <option value="invite_only">Invite-only</option>
          </Dropdown>
        </Field>
      </SettingsRow>
      <SettingsRow
        title="Member referrals"
        description="Allow eligible active members to invite someone. Individual referral permission is managed in the member roster."
      >
        <SettingSwitch
          label="Enable referrals"
          checked={referralsEnabled}
          disabled={loading || updateReferrals.isPending}
          onCheckedChange={(checked) => updateReferrals.mutate(checked)}
          error={updateReferrals.error?.message}
        />
      </SettingsRow>
      <SettingsRow title="Membership dues" description="The amount charged when a membership is activated. Use 0 for no charge.">
        <form className="flex min-w-0 flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); updateDues.mutate(); }}>
          <Field label="Dues amount" error={updateDues.error?.message} className="w-40">
            <Input type="number" min="0" step="0.01" value={duesAmount} disabled={loading || updateDues.isPending} onChange={(event) => setDuesAmount(event.target.value)} />
          </Field>
          <Button type="submit" disabled={loading} loading={updateDues.isPending} loadingLabel="Saving…">Save dues</Button>
        </form>
      </SettingsRow>
    </Card>
  );
}

function membershipPolicyLabel(policy: MembershipPolicyEnum) {
  return { open: "Join instantly", request: "Request approval", invite_only: "Invite-only" }[policy];
}
