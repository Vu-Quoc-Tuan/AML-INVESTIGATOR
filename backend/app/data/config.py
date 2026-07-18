"""Configuration for the shared synthetic-data repository."""

from dataclasses import dataclass, field


DEFAULT_OWNERSHIP_DOCUMENT_TYPES = frozenset(
    {
        "UBO_DECLARATION",
        "ARTICLES_OF_ASSOCIATION",
        "SHAREHOLDER_REGISTER",
        "BUSINESS_REGISTRATION",
        "SHARE_TRANSFER_AGREEMENT",
        "CORPORATE_STRUCTURE_DECLARATION",
    }
)


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    """Immutable integrity-policy configuration."""

    home_bank_id: str = "BANK-SHB-001"
    ownership_percentage_tolerance: float = 0.01
    allowed_ownership_document_types: frozenset[str] = field(
        default_factory=lambda: DEFAULT_OWNERSHIP_DOCUMENT_TYPES
    )

    def __post_init__(self) -> None:
        if not self.home_bank_id:
            raise ValueError("home_bank_id must be nonempty")
        if self.ownership_percentage_tolerance < 0:
            raise ValueError("ownership_percentage_tolerance must be nonnegative")
        object.__setattr__(
            self,
            "allowed_ownership_document_types",
            frozenset(self.allowed_ownership_document_types),
        )
