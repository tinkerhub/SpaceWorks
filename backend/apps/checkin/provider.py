"""How borrower-facing copy names the upstream check-in system and its required purpose.

Both are resolved per makerspace by `config.checkin_config` (the makerspace's own value,
else the deployment setting), so a makerspace on another check-in provider never sees
the reference deployment's names. The provider name falls back to "TinkerHub" only when
the roster URL is TinkerHub's own, so existing TinkerHub-backed installs keep their
wording without a new setting; any other upstream gets neutral copy until it is named.

`makerspace=None` answers for the deployment defaults.
"""

from apps.checkin.config import checkin_config


def provider_name(makerspace=None) -> str:
    return checkin_config(makerspace).provider


def required_purpose(makerspace=None) -> str:
    return checkin_config(makerspace).purpose
