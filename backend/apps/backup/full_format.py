"""Settings-free vocabulary for the separately authenticated full format."""

FULL_FORMAT = "spaceworks-deployment-full-v1"
FULL_PROTOCOL = "spaceworks-deployment-full-v1"
FULL_SIGNATURE_DOMAIN = b"spaceworks-deployment-full-manifest-v1\x00"
# Fixed serialized metadata limits shared by the producer and installed receiver.
MANIFEST_MAX_BYTES = 64 * 1024 * 1024
CONTINUITY_MAX_BYTES = 1024 * 1024
COMPOUND_UNSUPPORTED = (
    "Restore refused [compound_host_unsupported]: this host has no installed "
    "sovereign compound restore coordinator."
)
