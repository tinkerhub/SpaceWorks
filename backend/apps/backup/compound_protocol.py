"""Version vocabulary shared by compound producers and host capability installers."""


PROTOCOL_FAMILY = "spaceworks-lane-e-b1-v"
PROTOCOL_VERSION_NUMBER = 2
PROTOCOL_VERSION = f"{PROTOCOL_FAMILY}{PROTOCOL_VERSION_NUMBER}"

# Independent source-capture binding requires v2 on both producer and host.
# Keep a closed range so widening compatibility remains an explicit change.
SUPPORTED_PROTOCOL_MINIMUM = PROTOCOL_VERSION
SUPPORTED_PROTOCOL_MAXIMUM = PROTOCOL_VERSION
