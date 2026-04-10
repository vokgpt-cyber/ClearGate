"""Placeholder — this router previously hosted iter3.2 selection diagnostic
endpoints that tee'd frontend breadcrumbs into
``backend/logs/selection-diagnostic.jsonl``. The endpoints were removed
after the selection-popover bug was fixed.

The module is kept as an empty placeholder because the sandboxed build
environment could not physically delete it at cleanup time. It has no
router exported and is no longer imported from ``app.main``. Safe to
``rm`` from a real shell.
"""
