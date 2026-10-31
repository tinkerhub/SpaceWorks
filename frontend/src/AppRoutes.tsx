import type { ReactNode } from "react";
import { Route, Routes, useLocation } from "react-router-dom";

import { AboutPage } from "./features/AboutPage";
import { PublicBookingsPage } from "./features/bookings/PublicBookingsPage";
import { PublicEventFeedbackPage } from "./features/inventory/PublicEventFeedbackPage";
import { PublicEventsPage } from "./features/inventory/PublicEventsPage";
import { PublicInventoryPage } from "./features/inventory/PublicInventoryPage";
import { PublicMachinesPage } from "./features/inventory/PublicMachinesPage";
import { PublicMachineServicePage } from "./features/machineService/PublicMachineServicePage";
import { PublicRequestStatusPage } from "./features/inventory/PublicRequestStatusPage";
import { PublicSelfCheckoutPage } from "./features/inventory/PublicSelfCheckoutPage";
import { ArchivedPayments } from "./features/members/ArchivedPayments";
import { MyRequestsPage } from "./features/requests/MyRequestsPage";
import { MemberArea } from "./features/members/MemberArea";
import { PublicPrintRequestPage } from "./features/printing/PublicPrintRequestPage";
import { PublicOrganizationPage } from "./features/organizations/PublicOrganizationPage";
import { OrganizationInvitationRedeemPage } from "./features/organizations/OrganizationInvitationRedeemPage";
import { KioskPage, ScannerPage, SuperadminPage } from "./features/staff/PlatformApps";
import { ResetPasswordPage } from "./features/staff/ResetPasswordPage";
import { StaffApp } from "./features/staff/StaffApp";
import { EventCheckInStationPage } from "./features/events/EventCheckInStationPage";
import { PublicStatsPage } from "./features/stats/PublicStatsPage";
import { NotFoundPage } from "./components/NotFoundPage";
import { RequireModule } from "./lib/modules";

// One module key per optional public page. A page whose module is off is a 404 -- it must
// not render and fire requests the backend refuses.
const events = (page: ReactNode) => <RequireModule module="events">{page}</RequireModule>;
const machines = <RequireModule module="machines"><PublicMachinesPage /></RequireModule>;
const bookings = <RequireModule module="bookings"><PublicBookingsPage /></RequireModule>;
const print = <RequireModule module="printing"><PublicPrintRequestPage /></RequireModule>;
const machineService = <RequireModule module="machines"><RequireModule module="machine_service"><PublicMachineServicePage /></RequireModule></RequireModule>;

export function AppRoutes({ mode, landing }: { mode: "single" | "central"; landing: ReactNode }) {
  const location = useLocation();
  if (location.pathname === "/member/archived") {
    return <Routes><Route path="/member/archived" element={<ArchivedPayments />} /></Routes>;
  }
  if (location.pathname.startsWith("/organization-invitations/redeem/")) {
    return <Routes><Route path="/organization-invitations/redeem/:token" element={<OrganizationInvitationRedeemPage />} /></Routes>;
  }
  if (mode === "single") return <Routes>
    <Route path="/" element={<PublicInventoryPage />} />
    <Route path="/checkout" element={<PublicSelfCheckoutPage />} />
    <Route path="/my-requests" element={<MyRequestsPage />} />
    <Route path="/request" element={<RequireModule module="request_workflow"><PublicRequestStatusPage /></RequireModule>} />
    <Route path="/events" element={events(<PublicEventsPage />)} />
    <Route path="/events/:publicToken/feedback" element={events(<PublicEventFeedbackPage />)} />
    <Route path="/event-check-in/:stationToken" element={events(<EventCheckInStationPage />)} />
    <Route path="/machines" element={machines} />
    <Route path="/machine-service" element={machineService} />
    <Route path="/bookings" element={bookings} />
    <Route path="/print" element={print} />
    <Route path="/member" element={<MemberArea />} />
    <Route path="/stats" element={<PublicStatsPage />} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/admin/*" element={<StaffApp />} />
    <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
    <Route path="/scanner" element={<ScannerPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
  return <Routes>
    <Route path="/" element={landing} />
    <Route path="/about" element={<AboutPage />} />
    <Route path="/o/:organizationSlug" element={<PublicOrganizationPage />} />
    <Route path="/m/:slug" element={<PublicInventoryPage />} />
    <Route path="/m/:slug/checkout" element={<PublicSelfCheckoutPage />} />
    <Route path="/m/:slug/my-requests" element={<MyRequestsPage />} />
    <Route path="/m/:slug/request" element={<RequireModule module="request_workflow"><PublicRequestStatusPage /></RequireModule>} />
    <Route path="/m/:slug/events" element={events(<PublicEventsPage />)} />
    <Route path="/m/:slug/events/:publicToken/feedback" element={events(<PublicEventFeedbackPage />)} />
    <Route path="/m/:slug/event-check-in/:stationToken" element={events(<EventCheckInStationPage />)} />
    <Route path="/m/:slug/machines" element={machines} />
    <Route path="/m/:slug/machine-service" element={machineService} />
    <Route path="/m/:slug/bookings" element={bookings} />
    <Route path="/m/:slug/admin/*" element={<StaffApp />} />
    <Route path="/m/:slug/print" element={print} />
    <Route path="/m/:slug/member" element={<MemberArea />} />
    <Route path="/member" element={<MemberArea />} />
    <Route path="/m/:slug/stats" element={<PublicStatsPage />} />
    <Route path="/kiosk/:slug" element={<KioskPage />} />
    <Route path="/reset-password" element={<ResetPasswordPage />} />
    <Route path="/admin/*" element={<StaffApp />} />
    <Route path="/guest-admin/*" element={<StaffApp guestOnly />} />
    <Route path="/scanner" element={<ScannerPage />} />
    <Route path="/superadmin" element={<SuperadminPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes>;
}
