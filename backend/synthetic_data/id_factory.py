"""Stable, deterministic ID generation."""

from __future__ import annotations

from collections import defaultdict


class IDFactory:
    """Monotonic counters produce stable IDs within a single generation run.

    With a fixed seed and fixed generation order, the same logical entity
    always receives the same ID across runs.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    def next(self, prefix: str, width: int = 6) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:0{width}d}"

    def customer(self) -> str:
        return self.next("CUST", 6)

    def company(self) -> str:
        return self.next("COMP", 6)

    def account(self) -> str:
        return self.next("ACCT", 6)

    def transaction(self) -> str:
        return self.next("TXN", 8)

    def address(self) -> str:
        return self.next("ADDR", 6)

    def kyc_profile(self) -> str:
        return self.next("KYC", 6)

    def document(self) -> str:
        return self.next("DOC", 6)

    def ownership(self) -> str:
        return self.next("OWN", 6)

    def relationship(self) -> str:
        return self.next("REL", 6)

    def watchlist(self) -> str:
        return self.next("WL", 6)

    def scenario(self) -> str:
        return self.next("SCN", 3)

    def device(self) -> str:
        return self.next("DEV", 8)

    def bank(self) -> str:
        return self.next("BANK", 3)

    def reset(self) -> None:
        self._counters.clear()
