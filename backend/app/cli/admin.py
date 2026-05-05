"""``cleargate-admin`` — pilot-only user administration CLI.

The pilot has no self-registration endpoint (see ``app/routers/auth.py``);
all accounts are provisioned out-of-band by an operator through this
command.  The CLI talks directly to the same SQLite database the FastAPI
app uses, so it works whether you run it inside the backend container
(``docker exec cleargate-backend cleargate-admin ...``) or from a local
dev venv with ``pip install -e backend``.

Commands
--------
create-user    Add a new user; prompts for the password if not supplied.
list-users     Print user_id / username / active / created_at as a table.
reset-password Replace a user's password (forces re-login on next request).
set-active     Enable or disable a user without deleting the row.
delete-user    Hard-delete a user row.  Requires --yes or interactive confirm.
seed           One-shot idempotent seeding used by the pilot installer.

Exit codes
----------
0  success
1  user not found / duplicate / validation failure
2  unexpected runtime error (DB path, permissions, etc.)

Security notes
--------------
- Passwords read from stdin via ``getpass.getpass`` are never echoed.
- We deliberately avoid printing the Argon2 hash or the plaintext.
- ``--password`` is accepted as an argument for non-interactive seeding,
  but should NEVER be used on a shared shell history — prefer the
  interactive prompt or ``--password-stdin`` which reads from stdin
  without leaving a trace in ``.bash_history`` / ``doskey``.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

# We import lazily for two reasons:
#   1. The CLI must work even if the full app can't start (e.g. missing
#      ML models in the image) — deferring imports avoids dragging in
#      spaCy/presidio just to hash a password.
#   2. Keeps ``--help`` snappy for operators.


# ----------------------------------------------------------------------
# DB path resolution
# ----------------------------------------------------------------------


def _resolve_db_path(override: str | None) -> Path:
    """Return the path to ``users.db``.

    Precedence, highest first:
      1. ``--db`` command-line flag (explicit, wins always).
      2. ``CLEARGATE_USERS_DB`` environment variable (CI / tests).
      3. ``settings.session_store_dir / users.db`` — same logic the
         FastAPI app uses at startup, so the CLI is guaranteed to hit
         the same file the running backend reads.

    We resolve the path early and fail fast with a clear message if the
    file is missing, rather than letting sqlite3 create an empty DB in
    some random working directory.
    """
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("CLEARGATE_USERS_DB")
    if env:
        return Path(env).expanduser().resolve()

    # Mirror main.py's lifespan logic.
    from app.config import settings

    store_dir = Path(settings.session_store_dir)
    if not store_dir.is_absolute():
        store_dir = Path(__file__).resolve().parent.parent.parent / store_dir
    return (store_dir / "users.db").resolve()


def _open_store(db_path: Path):
    """Open the UserStore, creating the directory if needed.

    Returns a live :class:`UserStore`.  Caller is responsible for
    ``close()`` — we wrap every command in a ``try/finally`` below.
    """
    from app.services.user_store import UserStore

    # UserStore handles schema creation on a fresh DB, so the seed
    # command works on a clean install too.
    return UserStore(db_path=db_path)


# ----------------------------------------------------------------------
# Password helpers
# ----------------------------------------------------------------------


def _hash_password(plaintext: str) -> str:
    """Hash a password with Argon2id using the app's parameters.

    We construct a :class:`PasswordHasher` directly rather than going
    through :class:`AuthService` because the service insists on a
    signing secret (used for session cookies), and the CLI never issues
    cookies.
    """
    if not plaintext:
        raise ValueError("password cannot be empty")
    if len(plaintext) < 8:
        raise ValueError("password must be at least 8 characters")

    from argon2 import PasswordHasher

    from app.services.auth import (
        _ARGON2_HASH_LEN,
        _ARGON2_MEMORY_COST,
        _ARGON2_PARALLELISM,
        _ARGON2_SALT_LEN,
        _ARGON2_TIME_COST,
    )

    hasher = PasswordHasher(
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_COST,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_ARGON2_HASH_LEN,
        salt_len=_ARGON2_SALT_LEN,
    )
    return hasher.hash(plaintext)


def _read_password(args: argparse.Namespace, prompt: str) -> str:
    """Source a password from (in order): ``--password``, ``--password-stdin``, TTY prompt.

    The stdin mode consumes the whole remaining stdin buffer and strips
    a single trailing newline.  It is the recommended entry point for
    scripted seeding because it does not leave the password in shell
    history or ``/proc/<pid>/cmdline``.
    """
    if getattr(args, "password", None):
        return args.password
    if getattr(args, "password_stdin", False):
        data = sys.stdin.read()
        # Strip exactly one trailing newline — some shells add \n on
        # ``echo``, but the operator might also pipe from a file that
        # intentionally ends with newline-less content.
        if data.endswith("\n"):
            data = data[:-1]
        if data.endswith("\r"):
            data = data[:-1]
        return data
    first = getpass.getpass(f"{prompt}: ")
    second = getpass.getpass(f"{prompt} (confirm): ")
    if first != second:
        raise ValueError("passwords did not match")
    return first


# ----------------------------------------------------------------------
# Subcommand handlers
# ----------------------------------------------------------------------


def cmd_create_user(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        existing = store.get_by_username(args.username)
        if existing is not None:
            print(
                f"error: user '{args.username}' already exists (id={existing.user_id})",
                file=sys.stderr,
            )
            return 1
        try:
            password = _read_password(args, "New password")
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        try:
            password_hash = _hash_password(password)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        try:
            role = "admin" if args.admin else "lawyer"
            rec = store.create_user(
                username=args.username,
                password_hash=password_hash,
                is_active=not args.inactive,
                role=role,
            )
        except sqlite3.IntegrityError:
            # Race: someone else created the same username between the
            # get_by_username check and the INSERT. Report as duplicate.
            print(
                f"error: user '{args.username}' already exists (race)",
                file=sys.stderr,
            )
            return 1
        print(f"created user '{rec.username}'  id={rec.user_id}  active={rec.is_active}  role={rec.role}")
        return 0
    finally:
        store.close()


def cmd_list_users(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        users = store.list_users()
        if not users:
            print("(no users)")
            return 0
        # Simple fixed-width table — no external dep, alignment is fine
        # for the handful of pilot accounts we care about.
        header = f"{'username':<24} {'user_id':<38} {'active':<6} {'created_at':<25}"
        print(header)
        print("-" * len(header))
        for u in users:
            active = "yes" if u.is_active else "no"
            print(
                f"{u.username:<24} {u.user_id:<38} {active:<6} "
                f"{u.created_at.isoformat():<25}"
            )
        print(f"\n({len(users)} user{'s' if len(users) != 1 else ''})")
        return 0
    finally:
        store.close()


def cmd_reset_password(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        user = store.get_by_username(args.username)
        if user is None:
            print(f"error: user '{args.username}' not found", file=sys.stderr)
            return 1
        try:
            password = _read_password(args, f"New password for {user.username}")
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        try:
            password_hash = _hash_password(password)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not store.update_password(user.user_id, password_hash):
            # Should be impossible given the get_by_username above, but
            # surface it as a clear error rather than a silent success.
            print(
                f"error: password update affected 0 rows for id={user.user_id}",
                file=sys.stderr,
            )
            return 2
        print(f"password reset for '{user.username}'")
        return 0
    finally:
        store.close()


def cmd_set_active(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        user = store.get_by_username(args.username)
        if user is None:
            print(f"error: user '{args.username}' not found", file=sys.stderr)
            return 1
        target = not args.inactive  # --inactive flips to False, default True
        if user.is_active == target:
            print(
                f"user '{user.username}' already "
                f"{'active' if target else 'inactive'} — nothing to do"
            )
            return 0
        store.set_active(user.user_id, target)
        print(f"user '{user.username}' is now {'active' if target else 'inactive'}")
        return 0
    finally:
        store.close()


def cmd_delete_user(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        user = store.get_by_username(args.username)
        if user is None:
            print(f"error: user '{args.username}' not found", file=sys.stderr)
            return 1
        if not args.yes:
            # Deliberate friction: deleting a user in a legal-tech app
            # nukes their session history too (via cascade on the
            # backend side).  Operators should think twice.
            ans = input(
                f"really delete user '{user.username}' (id={user.user_id})? [y/N] "
            )
            if ans.strip().lower() not in ("y", "yes"):
                print("aborted")
                return 1
        store.delete_user(user.user_id)
        print(f"deleted user '{user.username}'")
        return 0
    finally:
        store.close()


def cmd_set_role(args: argparse.Namespace) -> int:
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        user = store.get_by_username(args.username)
        if user is None:
            print(f"error: user '{args.username}' not found", file=sys.stderr)
            return 1
        store.set_role(user.user_id, args.role)
        print(f"set role for '{user.username}' to '{args.role}'")
        return 0
    finally:
        store.close()


def cmd_seed(args: argparse.Namespace) -> int:
    """Idempotent seeding helper used by the pilot installer.

    Creates the named user with the supplied password iff it does not
    already exist.  Never overwrites an existing row — operators who
    want to reset a password should use ``reset-password`` explicitly.

    ``--if-empty`` makes the whole command a no-op unless the users
    table is empty; this is what the installer uses so re-running
    ``install.bat`` on an already-populated pilot does not silently add
    new rows.
    """
    db_path = _resolve_db_path(args.db)
    store = _open_store(db_path)
    try:
        if args.if_empty and store.count() > 0:
            print(f"skipped: users table already has {store.count()} row(s)")
            return 0
        existing = store.get_by_username(args.username)
        if existing is not None:
            print(f"skipped: user '{args.username}' already exists")
            return 0
        try:
            password = _read_password(args, f"Password for seeded user {args.username}")
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        try:
            password_hash = _hash_password(password)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        rec = store.create_user(
            username=args.username,
            password_hash=password_hash,
            is_active=True,
            role="admin" if args.admin else "lawyer",
        )
        print(f"seeded user '{rec.username}'  id={rec.user_id}")
        return 0
    finally:
        store.close()


# ----------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------


def _add_password_flags(sp: argparse.ArgumentParser) -> None:
    """Add the shared ``--password`` / ``--password-stdin`` flags.

    Extracted because three subcommands use them and it keeps the help
    text consistent.  Declared mutually exclusive so operators cannot
    accidentally pass both and wonder which one won.
    """
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--password",
        help="Password argument (INSECURE — appears in shell history).",
    )
    grp.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read password from stdin (recommended for scripts).",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cleargate-admin",
        description="CLEARGATE pilot user administration.",
    )
    p.add_argument(
        "--db",
        help="Override path to users.db (else CLEARGATE_USERS_DB or settings).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # create-user
    sp = sub.add_parser("create-user", help="Create a new user.")
    sp.add_argument("username")
    sp.add_argument(
        "--inactive",
        action="store_true",
        help="Create the user disabled (cannot log in until set-active).",
    )
    sp.add_argument(
        "--admin",
        action="store_true",
        help="Make this user an admin (role='admin' instead of 'lawyer').",
    )
    _add_password_flags(sp)
    sp.set_defaults(func=cmd_create_user)

    # list-users
    sp = sub.add_parser("list-users", help="List all users.")
    sp.set_defaults(func=cmd_list_users)

    # reset-password
    sp = sub.add_parser("reset-password", help="Replace a user's password.")
    sp.add_argument("username")
    _add_password_flags(sp)
    sp.set_defaults(func=cmd_reset_password)

    # set-active
    sp = sub.add_parser("set-active", help="Enable or disable a user.")
    sp.add_argument("username")
    sp.add_argument(
        "--inactive",
        action="store_true",
        help="Disable the user (default is to enable).",
    )
    sp.set_defaults(func=cmd_set_active)

    # set-role
    sp = sub.add_parser("set-role", help="Change a user's role.")
    sp.add_argument("--username", required=True, help="Username to modify.")
    sp.add_argument(
        "--role",
        required=True,
        choices=["admin", "lawyer"],
        help="New role for the user.",
    )
    sp.set_defaults(func=cmd_set_role)

    # delete-user
    sp = sub.add_parser("delete-user", help="Permanently remove a user.")
    sp.add_argument("username")
    sp.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    sp.set_defaults(func=cmd_delete_user)

    # seed
    sp = sub.add_parser(
        "seed",
        help="Idempotent seed used by the pilot installer.",
    )
    sp.add_argument("--username", required=True)
    sp.add_argument(
        "--if-empty",
        action="store_true",
        help="Only seed if the users table is currently empty.",
    )
    sp.add_argument(
        "--admin",
        action="store_true",
        help="Seed the user with admin role.",
    )
    _add_password_flags(sp)
    sp.set_defaults(func=cmd_seed)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — last-ditch diagnostic
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
