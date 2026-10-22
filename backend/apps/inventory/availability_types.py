class InsufficientStock(Exception):
    pass


class TrackingModeChangeRefused(Exception):
    """A product's tracking mode cannot change while it still carries stock state."""
