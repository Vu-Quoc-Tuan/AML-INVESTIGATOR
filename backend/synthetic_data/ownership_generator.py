"""Company ownership chains and entity relationships."""

from __future__ import annotations

from datetime import date
from typing import Optional

from synthetic_data.models import (
    BehavioralProfile,
    CompanyOwnership,
    EntityRelationship,
    EntityType,
)
from synthetic_data.world import WorldState


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _add_relationship(
    world: WorldState,
    source_entity_id: str,
    target_entity_id: str,
    relationship_type: str,
    valid_from: date,
    confidence: float = 0.9,
    source: str = "kyc_file",
) -> EntityRelationship:
    rel = EntityRelationship(
        relationship_id=world.ids.relationship(),
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relationship_type=relationship_type,
        valid_from=valid_from,
        valid_to=None,
        source=source,
        confidence=confidence,
    )
    world.relationships[rel.relationship_id] = rel
    return rel


_OWNERSHIP_EVIDENCE_TYPES = frozenset(
    {"UBO_DECLARATION", "ARTICLES_OF_ASSOCIATION"}
)


def _find_ubo_doc(world: WorldState, company_id: str) -> Optional[str]:
    """Only UBO/articles evidence can verify ownership — not a business license alone."""
    for d in world.kyc_documents.values():
        if d.entity_id != company_id or d.document_type not in _OWNERSHIP_EVIDENCE_TYPES:
            continue
        status = (
            d.verification_status.value
            if hasattr(d.verification_status, "value")
            else d.verification_status
        )
        if status == "VERIFIED":
            return d.document_id
    for d in world.kyc_documents.values():
        if d.entity_id == company_id and d.document_type in _OWNERSHIP_EVIDENCE_TYPES:
            return d.document_id
    return None


def _has_ownership(world: WorldState, company_id: str) -> bool:
    return any(o.owned_company_id == company_id for o in world.ownerships.values())


def _ownership_sum(world: WorldState, company_id: str) -> float:
    return sum(
        o.ownership_percentage
        for o in world.ownerships.values()
        if o.owned_company_id == company_id and o.effective_to is None
    )


def _add_ownership(
    world: WorldState,
    *,
    owner_entity_id: str,
    owner_entity_type: EntityType,
    owned_company_id: str,
    percentage: float,
    effective_from: date,
    incomplete_ubo: bool = False,
) -> CompanyOwnership:
    src_doc = None if incomplete_ubo else _find_ubo_doc(world, owned_company_id)
    # Only attach document if it still exists
    if src_doc and src_doc not in world.kyc_documents:
        src_doc = None
    own = CompanyOwnership(
        ownership_id=world.ids.ownership(),
        owner_entity_id=owner_entity_id,
        owner_entity_type=owner_entity_type,
        owned_company_id=owned_company_id,
        ownership_percentage=round(percentage, 2),
        effective_from=effective_from,
        effective_to=None,
        source_document_id=src_doc,
        verified=not incomplete_ubo and src_doc is not None,
    )
    world.ownerships[own.ownership_id] = own
    return own


def generate_ownership_for_company(
    world: WorldState,
    company_id: str,
    *,
    incomplete_ubo: bool = False,
    force_layers: Optional[int] = None,
    replace_existing: bool = False,
) -> list[CompanyOwnership]:
    """Create ownership edges for one company summing to ~100% at the direct layer."""
    if _has_ownership(world, company_id) and not replace_existing:
        return [
            o for o in world.ownerships.values() if o.owned_company_id == company_id
        ]

    if replace_existing:
        drop = [
            oid
            for oid, o in world.ownerships.items()
            if o.owned_company_id == company_id
        ]
        for oid in drop:
            del world.ownerships[oid]

    rng = world.rng
    company = world.companies[company_id]
    created: list[CompanyOwnership] = []
    effective_from = company.incorporation_date
    customer_ids = list(world.customers.keys())
    if not customer_ids:
        return created

    layers = force_layers if force_layers is not None else (2 if rng.random() < 0.2 else 1)

    hold = None
    if layers >= 2:
        candidates = [
            c
            for c in world.companies.values()
            if c.company_id != company_id
            and c.behavioral_profile != BehavioralProfile.NEWLY_INCORPORATED_COMPANY
        ]
        if candidates:
            hold = _pick(rng, candidates)

    if hold is not None:
        pct_hold = round(rng.uniform(51, 80), 2)
        remaining = round(100.0 - pct_hold, 2)
        own_h = _add_ownership(
            world,
            owner_entity_id=hold.company_id,
            owner_entity_type=EntityType.COMPANY,
            owned_company_id=company_id,
            percentage=pct_hold,
            effective_from=effective_from,
            incomplete_ubo=incomplete_ubo,
        )
        created.append(own_h)
        _add_relationship(
            world, hold.company_id, company_id, "PARENT_COMPANY", effective_from
        )

        minority = _pick(rng, customer_ids)
        own_m = _add_ownership(
            world,
            owner_entity_id=minority,
            owner_entity_type=EntityType.CUSTOMER,
            owned_company_id=company_id,
            percentage=remaining,
            effective_from=effective_from,
            incomplete_ubo=incomplete_ubo,
        )
        created.append(own_m)
        _add_relationship(
            world, minority, company_id, "SHAREHOLDER", effective_from
        )

        # Ensure holding company itself has natural-person owners (once)
        if not incomplete_ubo:
            if not _has_ownership(world, hold.company_id):
                ubo = _pick(rng, customer_ids)
                own_u = _add_ownership(
                    world,
                    owner_entity_id=ubo,
                    owner_entity_type=EntityType.CUSTOMER,
                    owned_company_id=hold.company_id,
                    percentage=100.0,
                    effective_from=hold.incorporation_date,
                    incomplete_ubo=False,
                )
                created.append(own_u)
                _add_relationship(
                    world, ubo, hold.company_id, "UBO", hold.incorporation_date
                )
        else:
            _add_relationship(
                world,
                hold.company_id,
                company_id,
                "UNRESOLVED_UBO_CHAIN",
                effective_from,
                confidence=0.3,
                source="incomplete_kyc",
            )
            # Holding has no natural person UBO recorded
            if not _has_ownership(world, hold.company_id):
                # Leave holding without owners intentionally for incomplete evidence
                pass
        return created

    # Direct individual ownership summing to 100%
    n_owners = rng.randint(1, 3)
    owners = rng.sample(customer_ids, k=min(n_owners, len(customer_ids)))
    remaining = 100.0
    for i, oid in enumerate(owners):
        if i == len(owners) - 1:
            pct = remaining
        else:
            max_pct = remaining - 5 * (len(owners) - i - 1)
            pct = round(rng.uniform(5, max(5.01, max_pct)), 2)
            remaining = round(remaining - pct, 2)
        own = _add_ownership(
            world,
            owner_entity_id=oid,
            owner_entity_type=EntityType.CUSTOMER,
            owned_company_id=company_id,
            percentage=pct,
            effective_from=effective_from,
            incomplete_ubo=incomplete_ubo,
        )
        created.append(own)
        _add_relationship(
            world,
            oid,
            company_id,
            "UBO" if pct >= 25 else "SHAREHOLDER",
            effective_from,
            confidence=0.95 if not incomplete_ubo else 0.4,
            source="incomplete_kyc" if incomplete_ubo else "kyc_file",
        )
    return created


def generate_ownerships(world: WorldState) -> None:
    """Phase 2: ownership + representative relationships for all companies."""
    # First pass: all companies get direct ownership (stable sum = 100)
    company_ids = list(world.companies.keys())
    for company_id in company_ids:
        company = world.companies[company_id]
        incomplete = (
            company.behavioral_profile == BehavioralProfile.NEWLY_INCORPORATED_COMPANY
            and world.rng.random() < 0.3
        )
        # Prefer single-layer first so sums stay clean; sample multi-layer later
        generate_ownership_for_company(
            world, company_id, incomplete_ubo=incomplete, force_layers=1
        )

    # Second pass: upgrade a few to multi-layer without breaking existing holds
    for company_id in company_ids:
        if world.rng.random() > 0.2:
            continue
        company = world.companies[company_id]
        if company.behavioral_profile == BehavioralProfile.NEWLY_INCORPORATED_COMPANY:
            continue
        generate_ownership_for_company(
            world,
            company_id,
            incomplete_ubo=False,
            force_layers=2,
            replace_existing=True,
        )

    for company_id, company in world.companies.items():
        _add_relationship(
            world,
            company.representative_customer_id,
            company_id,
            "LEGAL_REPRESENTATIVE",
            company.incorporation_date,
            confidence=0.99,
            source="kyc_file",
        )

    customer_ids = list(world.customers.keys())
    n_links = min(80, max(0, len(customer_ids) // 5))
    for _ in range(n_links):
        a, b = world.rng.sample(customer_ids, 2)
        rel_type = _pick(world.rng, ("FAMILY", "BUSINESS_ASSOCIATE", "SHARED_ADDRESS"))
        if rel_type == "SHARED_ADDRESS":
            # Relationship must reflect a real shared address_id.
            shared_addr = world.customers[a].address_id
            world.customers[b].address_id = shared_addr
        _add_relationship(
            world,
            a,
            b,
            rel_type,
            world.customers[a].created_at.date(),
            confidence=round(world.rng.uniform(0.5, 0.9), 2),
            source="entity_resolution",
        )

    # A customer may participate in multiple shared-address edges. Normalize
    # every connected component after all edges are known so a later edge
    # cannot invalidate an earlier one.
    shared_graph: dict[str, set[str]] = {}
    for rel in world.relationships.values():
        if rel.relationship_type != "SHARED_ADDRESS":
            continue
        shared_graph.setdefault(rel.source_entity_id, set()).add(rel.target_entity_id)
        shared_graph.setdefault(rel.target_entity_id, set()).add(rel.source_entity_id)
    visited: set[str] = set()
    for start in shared_graph:
        if start in visited:
            continue
        stack = [start]
        component: list[str] = []
        while stack:
            entity_id = stack.pop()
            if entity_id in visited:
                continue
            visited.add(entity_id)
            component.append(entity_id)
            stack.extend(shared_graph.get(entity_id, ()))
        anchor = min(component)
        shared_address = world.customers[anchor].address_id
        for entity_id in component:
            world.customers[entity_id].address_id = shared_address
