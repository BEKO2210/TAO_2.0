"""
Operating modes for the swarm.

Mode is the single most important config knob. It determines
whether the system can sign transactions, send value, or merely
look at chain state. The default sits at the safest end and the
higher-risk modes are explicit opt-ins.

| Mode             | Wallet     | Signing  | Sends value | Default |
|------------------|------------|----------|-------------|---------|
| NO_WALLET        | none       | no       | no          | yes     |
| WATCH_ONLY       | public     | no       | no          | no      |
| MANUAL_SIGNING   | public     | external | no          | no      |
| AUTO_TRADING     | hot key    | yes      | yes         | no      |

A higher mode never automatically grants the lower modes' rights;
each mode is its own enforced contract.
"""

from __future__ import annotations

from enum import Enum


class WalletMode(str, Enum):
    """The four operating modes, ordered by capability.

    The ``str`` mixin lets the value round-trip through JSON / YAML
    / env vars without losing typing.
    """

    NO_WALLET = "NO_WALLET"
    WATCH_ONLY = "WATCH_ONLY"
    MANUAL_SIGNING = "MANUAL_SIGNING"
    AUTO_TRADING = "AUTO_TRADING"

    @property
    def can_sign(self) -> bool:
        """Whether this mode is permitted to sign transactions at all.

        ``MANUAL_SIGNING`` is borderline — the orchestrator prepares
        an unsigned plan but does not sign. Returning ``False`` here
        is correct: the *orchestrator* never signs in that mode.
        """
        return self is WalletMode.AUTO_TRADING

    @property
    def can_send_value(self) -> bool:
        """Whether this mode is permitted to broadcast value-moving
        transactions on the operator's behalf without further
        confirmation."""
        return self is WalletMode.AUTO_TRADING

    @property
    def needs_keystore(self) -> bool:
        """Whether this mode requires a hot key in the keystore."""
        return self is WalletMode.AUTO_TRADING

    @classmethod
    def from_str(cls, value: str | None) -> WalletMode:
        """Parse from string with a safe default. Unknown values
        coerce to the safest mode rather than raising — this is
        the right call for an env-var driven config because a
        typo should never silently grant more authority."""
        if not value:
            return cls.NO_WALLET
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.NO_WALLET
