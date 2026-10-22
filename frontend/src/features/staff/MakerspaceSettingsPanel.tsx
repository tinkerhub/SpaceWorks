import type { ReactNode } from "react";

import { SectionHeading, Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui";
import { moduleEnabled } from "../../lib/modules";
import { ApiClientsTelegramSettings } from "./ApiClientsTelegramSettings";
import {
  MakerspacePrintStatusSettings,
  MakerspaceStaffNotificationSettings,
  MakerspaceSuperadminAccessSettings,
} from "./MakerspaceAccessSettings";
import { MakerspaceBrandingSettings } from "./MakerspaceBrandingSettings";
import { MakerspaceBookingRulesSettings } from "./MakerspaceBookingRulesSettings";
import { MakerspaceBookingSettings } from "./MakerspaceBookingSettings";
import { MakerspaceCustomDomainSettings } from "./MakerspaceCustomDomainSettings";
import { MakerspaceEmailSettings } from "./MakerspaceEmailSettings";
import { MakerspaceFilamentSettings } from "./MakerspaceFilamentSettings";
import { MakerspaceFeatureSettings } from "./MakerspaceFeatureSettings";
import { MakerspaceGeofenceSettings } from "./MakerspaceGeofenceSettings";
import { MakerspaceGeneralSettings } from "./MakerspaceGeneralSettings";
import { IntegrationHealthPanel } from "./IntegrationHealthPanel";
import { MakerspaceLocationSettings } from "./MakerspaceLocationSettings";
import { MakerspaceMembershipSettings } from "./MakerspaceMembershipSettings";
import { MakerspacePaymentSettings } from "./MakerspacePaymentSettings";
import { MakerspacePublicStatsSettings } from "./MakerspacePublicStatsSettings";
import { MakerspaceSubdomainSettings } from "./MakerspaceSubdomainSettings";
import { MakerspaceWebhookSettings } from "./MakerspaceWebhookSettings";
import { MakerspaceArchiveRequestPanel } from "./MakerspaceArchiveRequestPanel";
import { EvidenceRetentionPanel } from "./EvidenceRetentionPanel";
import { NotificationDestinations } from "./NotificationDestinations";
import { NotificationMuteMatrix } from "./NotificationMuteMatrix";
import { NotificationRecipientPicker } from "./NotificationRecipientPicker";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";

type Props = {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  canManageMakerspace: boolean;
  /** Origin-locked site: console links drop the /m/<slug> prefix. */
  singleTenantLocked?: boolean;
};

type Section = { key: string; label: string; content: ReactNode };

export function MakerspaceSettingsPanel({ makerspace, isSuperadmin, canManageMakerspace, singleTenantLocked = false }: Props) {
  const settings = useStaffGet<Makerspace>(
    ["makerspace-settings", makerspace.id],
    `/admin/makerspaces/${makerspace.id}`,
  );
  const enabledModules = settings.data?.enabled_modules ?? makerspace.enabled_modules ?? [];
  // A card for a switched-off module is not rendered at all: its endpoints refuse, and
  // a settings form for a feature the space does not run is noise. A tab whose cards are
  // all switched off is not rendered either.
  const on = (key: string) => moduleEnabled(enabledModules, key);
  const shared = { makerspace, settings: settings.data, loading: settings.isLoading };

  const sections: Section[] = [
    {
      key: "general",
      label: "General",
      content: (
        <>
          <MakerspaceBrandingSettings {...shared} />
          <MakerspaceGeneralSettings {...shared} />
          <MakerspaceLocationSettings {...shared} />
          {on("membership") ? <MakerspaceMembershipSettings {...shared} /> : null}
          <MakerspaceFeatureSettings {...shared} />
          {/* Presence sessions are started by members, so the geofence only means
              something while the membership module is on. */}
          {on("membership") ? <MakerspaceGeofenceSettings {...shared} /> : null}
          <MakerspacePublicStatsSettings {...shared} />
          {/* Retention governs hardware issue/return evidence, so it lives with the
              makerspace's own settings rather than under any optional module. */}
          {on("evidence_uploads") && canManageMakerspace ? <EvidenceRetentionPanel makerspaceId={makerspace.id} /> : null}
        </>
      ),
    },
  ];
  if (on("bookings")) {
    sections.push({
      key: "bookings",
      label: "Bookings",
      content: (
        <>
          <MakerspaceBookingSettings {...shared} />
          <MakerspaceBookingRulesSettings makerspace={makerspace} />
        </>
      ),
    });
  }
  if (on("printing") || on("machine_service")) {
    sections.push({
      key: "machines",
      label: "Machines",
      content: (
        <>
          {on("printing") ? <MakerspacePrintStatusSettings {...shared} /> : null}
          {on("machine_service") ? <MakerspaceFilamentSettings {...shared} /> : null}
        </>
      ),
    });
  }
  sections.push({
    key: "notifications",
    label: "Notifications",
    content: (
      <>
        {on("email") ? <MakerspaceStaffNotificationSettings {...shared} /> : null}
        {on("email") ? <MakerspaceEmailSettings makerspace={makerspace} /> : null}
        <section className="grid min-w-0 gap-4">
          <SectionHeading title="Notification channels" description="Which events reach which people, and where they are delivered." />
          <NotificationMuteMatrix makerspaceId={makerspace.id} />
          <NotificationRecipientPicker makerspaceId={makerspace.id} />
          <NotificationDestinations availableChannels={enabledModules} makerspaceId={makerspace.id} />
        </section>
      </>
    ),
  });
  sections.push({
    key: "integrations",
    label: "Integrations",
    content: (
      <>
        {on("payments") ? <MakerspacePaymentSettings makerspace={settings.data ?? makerspace} /> : null}
        <IntegrationHealthPanel makerspace={makerspace} singleTenantLocked={singleTenantLocked} />
        {on("telegram") && canManageMakerspace ? <ApiClientsTelegramSettings makerspace={makerspace} /> : null}
        {on("slack") || on("mattermost") || on("discord") ? <MakerspaceWebhookSettings makerspace={makerspace} /> : null}
      </>
    ),
  });
  sections.push({
    key: "access",
    label: "Domain & access",
    content: (
      <>
        <MakerspaceSuperadminAccessSettings {...shared} isSuperadmin={isSuperadmin} />
        {settings.data?.platform_hosting === true ? (
          <MakerspaceSubdomainSettings makerspace={makerspace} settings={settings.data} />
        ) : null}
        <MakerspaceCustomDomainSettings {...shared} isSuperadmin={isSuperadmin} />
        {/* Destructive: always last on the page (it renders the danger zone). */}
        <MakerspaceArchiveRequestPanel makerspaceId={makerspace.id} canManageMakerspace={canManageMakerspace} />
      </>
    ),
  });

  return (
    <Panel title="Settings" description={`How ${makerspace.name} looks, who it notifies and what it connects to.`}>
      <Tabs defaultValue="general">
        <TabsList aria-label="Settings sections">
          {sections.map((section) => (
            <TabsTrigger key={section.key} value={section.key}>{section.label}</TabsTrigger>
          ))}
        </TabsList>
        {sections.map((section) => (
          <TabsContent key={section.key} value={section.key} className="grid min-w-0 gap-6">
            {section.content}
          </TabsContent>
        ))}
      </Tabs>
    </Panel>
  );
}
