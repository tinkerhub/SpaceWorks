"""Which exported columns hold JSON, by `(model_label, field_name)`.

Split out of `references.py` when that file crossed the repo's 300-line hard ceiling.
It is a pure data table with no logic and no imports from the rest of the package,
which makes it the cleanest thing to lift out: `references` re-exports `JSON_FIELDS`,
so every existing importer is unaffected.

A JSON column is listed here so the export and tenant-migration passes know to walk
into its contents rather than treat it as an opaque scalar. A new JSON field that is
missing from this set is invisible to those passes — the drift guards in
`tests/data_export` are what catch that.
"""

JSON_FIELDS = frozenset(
    {
        ("apiclients.ApiClient", "scopes"),
        ("apiclients.ApiClient", "allowed_origins"),
        ("apiclients.ApiKeyRequest", "allowed_origins"),
        ("audit.AuditLog", "meta"),
        # Phase 7 imported-actor provenance. Each holds actor_username,
        # actor_display, source_user_id and recorded_at.
        ("makerspaces.MakerspaceMembership", "witnessed_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "verified_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "activated_actor_snapshot"),
        ("makerspaces.MakerspaceMembership", "revoked_actor_snapshot"),
        ("bookings.BookableSpace", "custom_form"),
        ("bookings.Booking", "custom_answers"),
        ("events.Event", "custom_form"),
        ("events.EventRegistration", "custom_answers"),
        ("hardware_requests.PublicToolLoan", "asset_ids"),
        ("hardware_requests.PublicToolLoan", "qr_ids"),
        ("machines.Machine", "service_file_policy"),
        ("machines.Machine", "type_payload"),
        ("machines.MachineServiceRequest", "capability_payload"),
        ("machines.MachineType", "capability_config"),
        ("makerspaces.Makerspace", "cors_allowed_origins"),
        ("makerspaces.Makerspace", "enabled_modules"),
        ("makerspaces.Makerspace", "enabled_features"),
        ("makerspaces.Makerspace", "resource_limit_overrides"),
        ("makerspaces.Makerspace", "theme_config"),
        ("makerspaces.Makerspace", "branding_config"),
        ("makerspaces.Makerspace", "presence_preset_minutes"),
        ("makerspaces.MakerspaceRole", "granted_actions"),
        ("makerspaces.MemberProfile", "interests"),
        ("makerspaces.MemberProfile", "languages"),
        ("makerspaces.MemberProfile", "education"),
        ("makerspaces.MemberProject", "links"),
        ("tenant_migration.ExternalTenantReference", "snapshot"),
    }
)
