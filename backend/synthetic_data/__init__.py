"""Synthetic banking world generator for AML investigation systems.

All identities, documents, accounts, and companies are fictitious.
Generation is fully deterministic given ``random_seed``.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__", "generate_world"]


def generate_world(config=None, **kwargs):
    """Generate a complete synthetic banking world and optionally write to disk.

    See :func:`synthetic_data.pipeline.generate_world` for details.
    """
    from synthetic_data.pipeline import generate_world as _generate_world

    return _generate_world(config=config, **kwargs)
