"""Synthetic sanctions / PEP / watchlist entries (entirely fictitious)."""

from __future__ import annotations

from datetime import date, timedelta

from synthetic_data.config import FAKE_FIRST_NAMES, FAKE_LAST_NAMES
from synthetic_data.models import ListType, WatchlistEntry, WatchlistStatus
from synthetic_data.world import WorldState


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _fake_person_name(rng) -> str:
    return f"{_pick(rng, FAKE_LAST_NAMES)} {_pick(rng, FAKE_FIRST_NAMES)} {_pick(rng, FAKE_FIRST_NAMES)}"


def generate_watchlist(world: WorldState, scenario_specs: list | None = None) -> None:
    """Phase 5: watchlist entries + optional near-matches for screening tests."""
    rng = world.rng
    cfg = world.config
    scenario_specs = scenario_specs or []

    # Baseline fictitious sanctions / PEP entries (no real persons)
    for i in range(40):
        list_type = _pick(
            rng,
            (ListType.SANCTIONS, ListType.PEP, ListType.WATCHLIST, ListType.ADVERSE_MEDIA),
        )
        name = _fake_person_name(rng)
        dob = date(rng.randint(1950, 1995), rng.randint(1, 12), rng.randint(1, 28))
        entry = WatchlistEntry(
            watchlist_id=world.ids.watchlist(),
            list_type=list_type,
            full_name=name,
            aliases=[f"{name.split()[0]} {_pick(rng, FAKE_FIRST_NAMES)}"] if rng.random() < 0.4 else [],
            date_of_birth=dob,
            nationalities=[_pick(rng, ("VN", "XX", "ZZ", "CY", "RU", "IR"))],
            document_numbers=[f"WLDOC{rng.randint(1000000, 9999999)}"] if rng.random() < 0.5 else [],
            addresses=[f"Unknown District {rng.randint(1, 99)}, Demo City"],
            company_registration_number=None,
            source_name=_pick(
                rng,
                (
                    "DEMO-SANCTIONS-LIST",
                    "DEMO-PEP-REGISTRY",
                    "DEMO-INTERNAL-WATCH",
                    "DEMO-ADVERSE-INDEX",
                ),
            ),
            effective_from=date(2015, 1, 1) + timedelta(days=rng.randint(0, 3000)),
            effective_to=None,
            status=WatchlistStatus.ACTIVE,
            screening_dependency="available",
        )
        world.watchlist[entry.watchlist_id] = entry

    # Fictitious sanctioned company registrations
    for _ in range(10):
        entry = WatchlistEntry(
            watchlist_id=world.ids.watchlist(),
            list_type=ListType.SANCTIONS,
            full_name=f"DEMO ENTITY {_pick(rng, FAKE_LAST_NAMES)} HOLDINGS",
            aliases=[],
            date_of_birth=None,
            nationalities=["XX"],
            document_numbers=[],
            addresses=["Offshore Demo Zone"],
            company_registration_number=f"OFF{rng.randint(10000000, 99999999)}",
            source_name="DEMO-SANCTIONS-LIST",
            effective_from=date(2018, 6, 1),
            effective_to=None,
            status=WatchlistStatus.ACTIVE,
            screening_dependency="available",
        )
        world.watchlist[entry.watchlist_id] = entry

    # High-risk foreign bank alias for graph screening demos
    bank_entry = WatchlistEntry(
        watchlist_id=world.ids.watchlist(),
        list_type=ListType.WATCHLIST,
        full_name="FOREIGN HIGH RISK BANK DEMO",
        aliases=["HR Foreign Bank Demo", "BANK-FOREIGN-HR-88"],
        date_of_birth=None,
        nationalities=[cfg.high_risk_foreign_country],
        document_numbers=[],
        addresses=["Demo Jurisdiction CY"],
        company_registration_number=None,
        source_name="DEMO-INTERNAL-WATCH",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        status=WatchlistStatus.ACTIVE,
        screening_dependency="available",
    )
    world.watchlist[bank_entry.watchlist_id] = bank_entry

    # For incomplete-evidence scenarios: mark a dependency unavailable
    # Do NOT create a NO_MATCH result — only mark dependency status.
    for spec in scenario_specs:
        if spec.scenario_type.value == "INCOMPLETE_EVIDENCE" or (
            hasattr(spec.scenario_type, "name")
            and spec.scenario_type == "INCOMPLETE_EVIDENCE"
        ):
            dep = WatchlistEntry(
                watchlist_id=world.ids.watchlist(),
                list_type=ListType.SANCTIONS,
                full_name="SCREENING DEPENDENCY PLACEHOLDER",
                aliases=[],
                date_of_birth=None,
                nationalities=[],
                document_numbers=[],
                addresses=[],
                company_registration_number=None,
                source_name="DEMO-SCREENING-GATEWAY",
                effective_from=cfg.world_start.date(),
                effective_to=None,
                status=WatchlistStatus.ACTIVE,
                screening_dependency="unavailable",
                related_entity_id=spec.notes.get("screening_entity_id"),
            )
            world.watchlist[dep.watchlist_id] = dep

        # Optional fuzzy near-name for one involved customer (not a hard hit label)
        if spec.scenario_key == "RAPID_FAN_IN_PASS_THROUGH" and spec.involved_entity_ids:
            # Create a watchlist name that is intentionally different — screening must decide
            near = WatchlistEntry(
                watchlist_id=world.ids.watchlist(),
                list_type=ListType.WATCHLIST,
                full_name=_fake_person_name(rng),
                aliases=["Synthetic Near Match Demo"],
                date_of_birth=date(1980, 5, 5),
                nationalities=["VN"],
                document_numbers=[],
                addresses=[],
                company_registration_number=None,
                source_name="DEMO-INTERNAL-WATCH",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                status=WatchlistStatus.ACTIVE,
                screening_dependency="available",
            )
            world.watchlist[near.watchlist_id] = near
