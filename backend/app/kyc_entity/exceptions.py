"""Domain errors for KYC/entity/UBO operations."""


class KycEntityError(RuntimeError):
    code = "KYC_ENTITY_ERROR"


class EntityNotFoundError(KycEntityError):
    code = "ENTITY_NOT_FOUND"


class EntityScopeViolationError(KycEntityError):
    code = "ENTITY_SCOPE_VIOLATION"


class EvidenceContractError(KycEntityError):
    code = "EVIDENCE_CONTRACT_ERROR"


class EvidenceConflictError(KycEntityError):
    code = "EVIDENCE_CONFLICT"


class OwnershipTraversalError(KycEntityError):
    code = "OWNERSHIP_TRAVERSAL_ERROR"
