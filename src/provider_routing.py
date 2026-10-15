"""Request-scoped limits and safe failures for opt-in OAuth source routing."""

from dataclasses import dataclass

from .credential_store import CredentialError

ROUTING_TIMEOUT_SECONDS = 120
SOURCE_ATTEMPTS = 2


class RoutingExhaustedError(CredentialError):
    """No eligible source succeeded within this request's routing budget."""

    def __init__(self, failures: list[tuple[str, str]], reason: str = "unavailable"):
        self.failures = tuple(failures)
        self.reason = reason
        detail = "; ".join(f"{source}: {status}" for source, status in failures)
        super().__init__(f"No available OAuth Provider ({reason}). {detail}")


class RoutingBudgetError(CredentialError):
    """The shared inference attempt budget is exhausted."""


@dataclass
class RequestBudget:
    remaining: int

    def consume(self) -> None:
        if self.remaining <= 0:
            raise RoutingBudgetError("The OAuth routing attempt budget is exhausted.")
        self.remaining -= 1
