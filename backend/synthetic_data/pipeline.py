"""Orchestrate the full generation pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from synthetic_data.config import GeneratorConfig
from synthetic_data.entity_generator import generate_entities
from synthetic_data.ground_truth import build_ground_truth
from synthetic_data.io_writer import write_world
from synthetic_data.ledger import fund_ledger_deficits
from synthetic_data.normal_transaction_generator import generate_normal_transactions
from synthetic_data.ownership_generator import generate_ownerships
from synthetic_data.scenario_injector import inject_all_scenarios
from synthetic_data.validators import assert_valid
from synthetic_data.watchlist_generator import generate_watchlist
from synthetic_data.world import WorldState


def generate_world(
    config: Optional[GeneratorConfig] = None,
    *,
    write: bool = True,
    output_dir: Optional[Path | str] = None,
    **kwargs: Any,
) -> WorldState:
    """Run all phases and optionally write output files.

    Extra ``kwargs`` override :class:`GeneratorConfig` fields
    (e.g. ``random_seed=42``, ``n_customers=2000``).

    Final customer/company counts are hard quotas. Normal transactions are
    generated first; scenario transactions are additive. There is no
    SYSTEM-FLOAT super-node. A final ledger reconcile only raises
    ``initial_balance`` is never rewritten from future activity; any required
    liquidity support is emitted as an explicit bank-settlement transaction.
    """
    if config is None:
        config = GeneratorConfig()
    for k, v in kwargs.items():
        if not hasattr(config, k):
            raise TypeError(f"Unknown config field: {k}")
        setattr(config, k, v)
    if output_dir is not None:
        config.output_dir = Path(output_dir)
    config.validate()

    world = WorldState.create(config)

    # Phase 1 — entities (exact quotas)
    generate_entities(world)

    # Phase 2 — ownership / relationships
    generate_ownerships(world)

    # Phase 3 — normal transactions from behavioral profiles
    generate_normal_transactions(world)

    # Phase 4 — scenario injection reuses reserved roster entities
    scenario_specs = inject_all_scenarios(world)

    # Phase 4b — ensure strict replay using visible funding, never hidden balance rewrites
    fund_ledger_deficits(world)

    # Phase 5 — watchlist
    generate_watchlist(world, scenario_specs)

    # Phase 6 — ground truth (separate artefact)
    build_ground_truth(world, scenario_specs)

    # Phase 7 — validate
    if config.run_validation:
        assert_valid(world)

    # Phase 8 — write
    if write:
        write_world(world, config.output_dir)

    return world


def checksum_for_seed(seed: int, **kwargs: Any) -> dict[str, str]:
    """Generate twice-free helper: produce world and return file checksums."""
    from synthetic_data.io_writer import write_world

    cfg = GeneratorConfig(random_seed=seed, **kwargs)
    world = generate_world(cfg, write=False)
    # write to temp-like dir under output
    out = Path(cfg.output_dir)
    return write_world(world, out)
