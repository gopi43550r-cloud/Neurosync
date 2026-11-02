"""NeuroSync evaluation package.

Measures how reliably the deterministic pipeline detects contradictions,
evaluates evidence sufficiency, and produces traceable conclusions.

Entry point::

    python -m evaluation.run_evaluation        # from the backend/ directory

The package is intentionally separate from ``app/`` (production code) and from
``app/tests/`` (unit tests). The curated datasets in ``datasets/`` are labelled
evaluation fixtures and are never loaded into a production database.
"""
