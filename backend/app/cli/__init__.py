"""Command-line utilities bundled with the CLEARGATE backend.

The only entry-point today is :mod:`app.cli.admin`, wired up as
``cleargate-admin`` in ``pyproject.toml``.  Pilot operators run it from
inside the backend container (``docker exec cleargate-backend
cleargate-admin ...``) or from a dev venv with the backend installed.
"""
