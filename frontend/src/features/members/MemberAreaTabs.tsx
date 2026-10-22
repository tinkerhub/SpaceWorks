import { useState, type ComponentProps, type ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";
import { MemberAccountSection } from "./MemberAccountSection";
import { MemberActivityPanel, type MemberActivity } from "./MemberActivity";
import { MembershipCards, type Membership, type Presence, type Waiver } from "./MemberAreaSections";
import { MemberDirectory } from "./MemberDirectory";
import { MemberPaymentRows, type MemberPayment } from "./MemberPayments";
import { MemberProfilePanel } from "./MemberProfilePanel";
import { MemberReferrals } from "./MemberReferrals";
import { PartnerEvents } from "./PartnerEvents";

type MemberAreaTabsProps = {
  /** Join / request / loading cards for this makerspace, shown first on the overview. */
  standing: ReactNode;
  username?: string;
  membership?: Membership;
  membershipOn: boolean;
  eventsOn: boolean;
  makerspaceId: number;
  makerspaceSlug: string;
  waiver?: Waiver;
  presence?: Presence;
  activity?: MemberActivity;
  payments?: MemberPayment[];
  accepting: boolean;
  presenceBusy: boolean;
  canStartPresence: boolean;
  checkoutPaymentId?: number;
  onAccept: () => void;
  onTogglePresence: () => void;
  onCheckout: (paymentId: number) => void;
  onSignedOut: () => void;
  referrals: ComponentProps<typeof MemberReferrals> | null;
};

/**
 * The signed-in member area as account tabs. Every panel stays mounted (inactive ones are
 * only hidden), so each section loads exactly as it did on the single long page and a
 * switch between tabs never refetches or drops a half-written form.
 */
export function MemberAreaTabs(props: MemberAreaTabsProps) {
  const { membership, membershipOn, eventsOn, makerspaceId, makerspaceSlug, activity, payments, username } = props;
  const active = membership?.membership_status === "active";
  const showActivity = Boolean(membership) && ((membershipOn && Boolean(activity)) || (eventsOn && active));
  const showProfile = Boolean(membership) && membershipOn && active && makerspaceId >= 0;
  const showPayments = Boolean(membership && payments?.length);
  const tabs = [
    { value: "overview", label: "Overview", show: true },
    { value: "activity", label: "Activity", show: showActivity },
    { value: "profile", label: "Profile", show: showProfile },
    { value: "payments", label: "Payments", show: showPayments },
    { value: "account", label: "Account", show: Boolean(username) },
  ].filter((tab) => tab.show);
  const [selected, setSelected] = useState("overview");
  const value = tabs.some((tab) => tab.value === selected) ? selected : "overview";
  const panel = "flex flex-col gap-5 data-[state=inactive]:hidden";

  return (
    <Tabs value={value} onValueChange={setSelected}>
      <TabsList aria-label="Member area sections">
        {tabs.map((tab) => <TabsTrigger key={tab.value} value={tab.value}>{tab.label}</TabsTrigger>)}
      </TabsList>
      <TabsContent value="overview" forceMount className={panel}>
        {props.standing}
        {membership && membershipOn ? (
          <MembershipCards
            membership={membership}
            waiver={props.waiver}
            presence={props.presence}
            accepting={props.accepting}
            presenceBusy={props.presenceBusy}
            canStartPresence={props.canStartPresence}
            onAccept={props.onAccept}
            onTogglePresence={props.onTogglePresence}
          />
        ) : null}
        {props.referrals ? <MemberReferrals {...props.referrals} /> : null}
      </TabsContent>
      {showActivity ? (
        <TabsContent value="activity" forceMount className={panel}>
          {membershipOn && activity ? <MemberActivityPanel activity={activity} makerspaceId={makerspaceId} makerspaceSlug={makerspaceSlug} /> : null}
          {eventsOn && active ? <PartnerEvents makerspaceId={makerspaceId} slug={makerspaceSlug} /> : null}
        </TabsContent>
      ) : null}
      {showProfile ? (
        <TabsContent value="profile" forceMount className={panel}>
          <MemberProfilePanel makerspaceId={makerspaceId} />
          <MemberDirectory makerspaceId={makerspaceId} />
        </TabsContent>
      ) : null}
      {showPayments && payments ? (
        <TabsContent value="payments" forceMount className={panel}>
          <AccountCard title="Payments" description="Charges and receipts for this makerspace.">
            <MemberPaymentRows payments={payments} checkoutPaymentId={props.checkoutPaymentId} onCheckout={props.onCheckout} />
          </AccountCard>
        </TabsContent>
      ) : null}
      {username ? (
        <TabsContent value="account" forceMount className={panel}>
          <MemberAccountSection username={username} onSignedOut={props.onSignedOut} />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}
