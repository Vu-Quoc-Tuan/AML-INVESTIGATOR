"""CLI entrypoint for synthetic banking data generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_data",
        description="Generate a synthetic banking world for AML investigation.",
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed (reproducible)")
    p.add_argument("--customers", type=int, default=2000, help="Final number of individual customers")
    p.add_argument("--companies", type=int, default=50, help="Final number of companies")
    p.add_argument(
        "--transactions",
        type=int,
        default=40_000,
        help="Target number of normal baseline transactions",
    )
    p.add_argument(
        "--external-accounts",
        type=int,
        default=1_000,
        help="Observed external counterparties (500-1500)",
    )
    p.add_argument(
        "--min-accounts",
        type=int,
        default=2500,
        help="Minimum final SHB-managed account count",
    )
    p.add_argument(
        "--max-accounts",
        type=int,
        default=3000,
        help="Maximum final SHB-managed account count",
    )
    p.add_argument(
        "--output",
        type=str,
        default="./data/generated",
        help="Output directory for CSV/JSONL/JSON files",
    )
    p.add_argument("--window-days", type=int, default=90, help="Transaction window length")
    p.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip post-generation validation (not recommended)",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="Build world in memory only (no files)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Ensure backend root is on path when run as module
    backend_root = Path(__file__).resolve().parent.parent
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from synthetic_data.config import GeneratorConfig
    from synthetic_data.pipeline import generate_world

    config = GeneratorConfig(
        random_seed=args.seed,
        n_customers=args.customers,
        n_companies=args.companies,
        n_transactions=args.transactions,
        n_external_accounts=args.external_accounts,
        min_accounts=args.min_accounts,
        max_accounts=args.max_accounts,
        output_dir=Path(args.output),
        window_days=args.window_days,
        run_validation=not args.skip_validation,
    )

    print(
        f"Generating synthetic world: seed={config.random_seed} "
        f"customers={config.n_customers} companies={config.n_companies} "
        f"target_tx={config.n_transactions} → {config.output_dir}"
    )
    world = generate_world(config, write=not args.no_write)
    print(
        f"Done. customers={len(world.customers)} companies={len(world.companies)} "
        f"shb_accounts={len(world.accounts)} "
        f"external_accounts={len(world.external_accounts)} "
        f"transactions={len(world.transactions)} scenarios={len(world.scenarios)}"
    )
    if not args.no_write:
        print(f"Files written to {config.output_dir.resolve()}")
        manifest = config.output_dir / "manifest.json"
        if manifest.exists():
            print(f"Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
