"""Settings-free reviewed schema of the X13 projection proof."""



PROJECTED_LABELS = frozenset(
    """accounts.User apiclients.ApiKeyRequest audit.AuditLog backup.MakerspaceArchiveRecipient
    bookings.BookableSpace bookings.Booking boxes.Box boxes.BoxScan
    boxes.QrCode boxes.QrScanEvent checkin.CheckinIdentity events.Event
    events.EventAttendanceCertificate events.EventCheckInEvent events.EventFeedbackResponse events.EventFeedbackSurvey
    events.EventRegistration events.EventSeries evidence.EvidenceObjectRetentionState evidence.EvidencePhoto
    evidence.EvidenceRetentionPolicy hardware_requests.HardwareRequest hardware_requests.HardwareRequestItem hardware_requests.HardwareRequestItemAsset
    hardware_requests.PublicProblemReport hardware_requests.PublicToolLoan hardware_requests.RequesterAccountability hardware_requests.ReturnEvent
    integrations.ChatTemplate integrations.DestinationCategoryScope integrations.DestinationMachineScope integrations.DestinationMachineTypeScope
    integrations.EmailTemplate integrations.MachineTypeEmailTemplate integrations.NotificationDestination inventory.Category
    inventory.InventoryAsset inventory.InventoryProduct machines.Machine machines.MachineConsumable
    machines.MachineConsumableAdjustment machines.MachineConsumablePool machines.MachineDocument machines.MachineErrorLog
    machines.MachineOperator machines.MachineServiceRequest machines.MachineType machines.MachineUsageEntry
    machines.MakerspaceMachineTypePricing machines.ServiceBucket machines.ServiceQueue machines.ServiceRequestConsumption
    machines.ServiceRequestFile maintenance.MaintenanceLog maintenance.MaintenanceLogDocument maintenance.MaintenanceSchedule
    makerspaces.Makerspace makerspaces.MakerspaceMembership makerspaces.MakerspaceWaiver makerspaces.MemberProfile
    makerspaces.MemberProject makerspaces.MembershipRequest notifications.Notification operations.InventoryAdjustment
    operations.QrPrintBatch operations.QrPrintBatchItem operations.ReportMetricRollup operations.StockTransfer
    operations.StockTransferLine operations.StocktakeLedgerEntry operations.StocktakeLine operations.StocktakeSession
    payments.MakerspacePaymentSettings payments.Payment presence.PresenceSession procurement.ToBuyItem
    procurement.ToBuyReceipt tenant_migration.ExternalTenantReference warranty.Warranty warranty.WarrantyDocument""".split()
)
POLYMORPHIC_LOCATIONS = frozenset({
    ("audit.AuditLog", "target_type+target_id"),
    ("boxes.QrCode", "target_type+target_id"),
    ("hardware_requests.PublicToolLoan", "target_type+target_id"),
    ("operations.QrPrintBatchItem", "target_type+target_id"),
})
SEMANTIC_LOCATIONS = POLYMORPHIC_LOCATIONS | frozenset({
    ('apiclients.ApiKeyRequest', 'json:allowed_origins'),
    ('audit.AuditLog', 'json:meta'),
    ('bookings.BookableSpace', 'json:custom_form'),
    ('bookings.Booking', 'json:custom_answers'),
    ('events.Event', 'json:badge_template'),
    ('events.Event', 'json:custom_form'),
    ('events.Event', 'json:series_override_fields'),
    ('events.EventFeedbackSurvey', 'json:answered_question_ids'),
    ('events.EventFeedbackSurvey', 'json:questions'),
    ('events.EventRegistration', 'json:custom_answers'),
    ('events.EventSeries', 'json:custom_form'),
    ('hardware_requests.PublicToolLoan', 'json:asset_ids'),
    ('hardware_requests.PublicToolLoan', 'json:qr_ids'),
    ('machines.Machine', 'json:service_file_policy'),
    ('machines.Machine', 'json:type_payload'),
    ('machines.MachineServiceRequest', 'json:capability_payload'),
    ('machines.MachineType', 'json:capability_config'),
    ('makerspaces.Makerspace', 'json:branding_config'),
    ('makerspaces.Makerspace', 'json:cors_allowed_origins'),
    ('makerspaces.Makerspace', 'json:enabled_features'),
    ('makerspaces.Makerspace', 'json:enabled_modules'),
    ('makerspaces.Makerspace', 'json:presence_preset_minutes'),
    ('makerspaces.Makerspace', 'json:resource_limit_overrides'),
    ('makerspaces.Makerspace', 'json:theme_config'),
    ('makerspaces.MakerspaceMembership', 'json:activated_actor_snapshot'),
    ('makerspaces.MakerspaceMembership', 'json:revoked_actor_snapshot'),
    ('makerspaces.MakerspaceMembership', 'json:verified_actor_snapshot'),
    ('makerspaces.MakerspaceMembership', 'json:witnessed_actor_snapshot'),
    ('makerspaces.MemberProfile', 'json:education'),
    ('makerspaces.MemberProfile', 'json:interests'),
    ('makerspaces.MemberProfile', 'json:languages'),
    ('makerspaces.MemberProject', 'json:links'),
    ('tenant_migration.ExternalTenantReference', 'json:snapshot'),
})
SEMANTIC_RESET_LOCATIONS = frozenset(
    ("makerspaces.Makerspace", "json:" + field) for field in (
        "cors_allowed_origins", "enabled_modules", "enabled_features", "resource_limit_overrides"
    )
)


def semantic_disposition(label, location):
    return "reset" if (label, location) in SEMANTIC_RESET_LOCATIONS else "preserve"
