"""Build ground-truth scenario records (isolated from feature tables)."""

from __future__ import annotations

from synthetic_data.models import GroundTruthScenario
from synthetic_data.scenario_injector import ScenarioSpec
from synthetic_data.world import WorldState


def build_ground_truth(world: WorldState, specs: list[ScenarioSpec]) -> list[GroundTruthScenario]:
    """Convert injector specs into stable ground-truth records with scenario IDs."""
    results: list[GroundTruthScenario] = []
    for spec in specs:
        gt = GroundTruthScenario(
            scenario_id=world.ids.scenario(),
            scenario_type=spec.scenario_type,
            start_time=spec.start_time,
            end_time=spec.end_time,
            involved_account_ids=list(spec.involved_account_ids),
            involved_entity_ids=list(spec.involved_entity_ids),
            suspicious_transaction_ids=list(spec.suspicious_transaction_ids),
            expected_alert_type=spec.expected_alert_type,
            expected_case_disposition=spec.expected_case_disposition,
            explanation=spec.explanation,
            typology_tags=list(spec.typology_tags),
            notes={
                **spec.notes,
                "scenario_key": spec.scenario_key,
            },
        )
        world.scenarios[gt.scenario_id] = gt
        results.append(gt)
    return results
