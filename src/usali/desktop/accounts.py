"""Local accounts and sign-in sessions (PRD A-1 to A-7, ADR-D1).

Plain SQL over `desktop.account` / `desktop.session` (d0002): not
org-scoped, so outside the ORM's tenancy hook. Everything that decides
what a person may DO stays in upstream's `role_assignment`, keyed by the
same `subject`.

`LocalAccountAdmin` implements upstream's `KeycloakAdmin` seam over these
tables, so upstream's onboarding and termination code creates and disables
desktop logins without knowing Keycloak is gone.
"""

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from usali.desktop.passwords import hash_secret, new_setup_code, normalise_recovery_code
from usali.keycloak_admin import KeycloakAdminError

SESSION_TTL = timedelta(hours=8)
SETUP_CODE_TTL = timedelta(hours=24)
# Ten wrong passwords in a row lock the account for fifteen minutes: slows a
# guesser to a crawl without letting a typo-prone owner lock themselves out
# for long. The recovery code always works, locked or not.
MAX_FAILURES = 10
LOCKOUT = timedelta(minutes=15)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class Account:
    subject: str
    username: str
    email: str | None
    full_name: str
    roles: tuple[str, ...]
    enabled: bool
    password_hash: str | None
    recovery_code_hash: str | None
    setup_code_hash: str | None
    setup_code_expires_at: datetime | None
    failed_attempts: int
    locked_until: datetime | None

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    def locked(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > now


@dataclass(frozen=True)
class SignInSession:
    session_id: str
    device_label: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


_COLUMNS = (
    "subject, username, email, full_name, realm_roles, enabled, password_hash, "
    "recovery_code_hash, setup_code_hash, setup_code_expires_at, failed_attempts, locked_until"
)


def _row_to_account(row: object) -> Account:
    r = row._mapping  # type: ignore[attr-defined]
    return Account(
        subject=r["subject"], username=r["username"], email=r["email"],
        full_name=r["full_name"], roles=tuple(r["realm_roles"] or ()), enabled=r["enabled"],
        password_hash=r["password_hash"], recovery_code_hash=r["recovery_code_hash"],
        setup_code_hash=r["setup_code_hash"], setup_code_expires_at=r["setup_code_expires_at"],
        failed_attempts=r["failed_attempts"], locked_until=r["locked_until"],
    )


def now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ accounts


def count_accounts(session: Session) -> int:
    return int(session.execute(text("SELECT count(*) FROM desktop.account")).scalar_one())


def get_account(session: Session, subject: str) -> Account | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM desktop.account WHERE subject = :s"), {"s": subject}
    ).first()
    return None if row is None else _row_to_account(row)


def find_by_login(session: Session, login: str) -> Account | None:
    """Sign-in accepts the username or the email, in any case."""
    row = session.execute(
        text(
            f"SELECT {_COLUMNS} FROM desktop.account "
            "WHERE username = lower(:l) OR lower(email) = lower(:l) LIMIT 1"
        ),
        {"l": login.strip()},
    ).first()
    return None if row is None else _row_to_account(row)


def list_accounts(session: Session) -> list[Account]:
    rows = session.execute(
        text(f"SELECT {_COLUMNS} FROM desktop.account ORDER BY created_at")
    ).all()
    return [_row_to_account(r) for r in rows]


def create_account(
    session: Session,
    *,
    username: str,
    email: str | None,
    full_name: str,
    roles: list[str],
    subject: str | None = None,
    password_hash: str | None = None,
) -> str:
    subject = subject or uuid.uuid4().hex
    session.execute(
        text(
            "INSERT INTO desktop.account "
            "(subject, username, email, full_name, realm_roles, password_hash, password_changed_at) "
            # The CAST: a parameter used twice must say its type, or Postgres
            # cannot infer it for the second use.
            "VALUES (:s, lower(:u), :e, :n, :r, CAST(:p AS text), "
            "CASE WHEN CAST(:p AS text) IS NULL THEN NULL ELSE now() END)"
        ),
        {"s": subject, "u": username.strip(), "e": email, "n": full_name.strip(),
         "r": list(roles), "p": password_hash},
    )
    return subject


def set_password_hash(session: Session, subject: str, password_hash: str) -> None:
    """A new password clears any setup code and any lockout."""
    session.execute(
        text(
            "UPDATE desktop.account SET password_hash = :p, password_changed_at = now(), "
            "setup_code_hash = NULL, setup_code_expires_at = NULL, "
            "failed_attempts = 0, locked_until = NULL WHERE subject = :s"
        ),
        {"p": password_hash, "s": subject},
    )


def set_recovery_code(session: Session, subject: str, code: str) -> None:
    session.execute(
        text("UPDATE desktop.account SET recovery_code_hash = :h WHERE subject = :s"),
        {"h": hash_secret(normalise_recovery_code(code)), "s": subject},
    )


def issue_setup_code(session: Session, subject: str) -> str:
    code = new_setup_code()
    session.execute(
        text(
            "UPDATE desktop.account SET setup_code_hash = :h, setup_code_expires_at = :x "
            "WHERE subject = :s"
        ),
        {"h": hash_secret(code.replace("-", "")), "x": now() + SETUP_CODE_TTL, "s": subject},
    )
    return code


def record_failure(session: Session, subject: str) -> None:
    session.execute(
        text(
            "UPDATE desktop.account SET failed_attempts = failed_attempts + 1, "
            "locked_until = CASE WHEN failed_attempts + 1 >= :max THEN :until "
            "ELSE locked_until END WHERE subject = :s"
        ),
        {"max": MAX_FAILURES, "until": now() + LOCKOUT, "s": subject},
    )


def clear_failures(session: Session, subject: str) -> None:
    session.execute(
        text(
            "UPDATE desktop.account SET failed_attempts = 0, locked_until = NULL "
            "WHERE subject = :s"
        ),
        {"s": subject},
    )


def set_roles(session: Session, subject: str, roles: list[str]) -> None:
    session.execute(
        text("UPDATE desktop.account SET realm_roles = :r WHERE subject = :s"),
        {"r": sorted(set(roles)), "s": subject},
    )


def disable(session: Session, subject: str) -> None:
    session.execute(
        text("UPDATE desktop.account SET enabled = false WHERE subject = :s"), {"s": subject}
    )
    revoke_all_sessions(session, subject)


# ------------------------------------------------------------------ sessions


def start_session(session: Session, subject: str, device_label: str) -> tuple[str, datetime]:
    session_id = secrets.token_urlsafe(24)
    expires = now() + SESSION_TTL
    session.execute(
        text(
            "INSERT INTO desktop.session (session_id, subject, device_label, expires_at) "
            "VALUES (:i, :s, :d, :x)"
        ),
        {"i": session_id, "s": subject, "d": device_label[:200] or "This computer", "x": expires},
    )
    return session_id, expires


def session_is_live(session: Session, session_id: str, subject: str) -> bool:
    return session.execute(
        text(
            "SELECT 1 FROM desktop.session s JOIN desktop.account a USING (subject) "
            "WHERE s.session_id = :i AND s.subject = :s AND s.revoked_at IS NULL "
            "AND s.expires_at > now() AND a.enabled"
        ),
        {"i": session_id, "s": subject},
    ).first() is not None


def touch_session(session: Session, session_id: str) -> None:
    session.execute(
        text(
            "UPDATE desktop.session SET last_seen_at = now() WHERE session_id = :i "
            "AND last_seen_at < now() - interval '1 minute'"
        ),
        {"i": session_id},
    )


def list_sessions(session: Session, subject: str) -> list[SignInSession]:
    rows = session.execute(
        text(
            "SELECT session_id, device_label, created_at, last_seen_at, expires_at "
            "FROM desktop.session WHERE subject = :s AND revoked_at IS NULL "
            "AND expires_at > now() ORDER BY last_seen_at DESC"
        ),
        {"s": subject},
    ).all()
    return [SignInSession(*r) for r in rows]


def revoke_session(session: Session, session_id: str, subject: str) -> bool:
    """Only the account's own sessions — the id alone proves nothing."""
    result = session.execute(
        text(
            "UPDATE desktop.session SET revoked_at = now() WHERE session_id = :i "
            "AND subject = :s AND revoked_at IS NULL"
        ),
        {"i": session_id, "s": subject},
    )
    return bool(getattr(result, "rowcount", 0))


def revoke_other_sessions(session: Session, subject: str, keep: str | None) -> None:
    session.execute(
        text(
            "UPDATE desktop.session SET revoked_at = now() WHERE subject = :s "
            "AND revoked_at IS NULL AND session_id IS DISTINCT FROM :k"
        ),
        {"s": subject, "k": keep},
    )


def revoke_all_sessions(session: Session, subject: str) -> None:
    session.execute(
        text(
            "UPDATE desktop.session SET revoked_at = now() "
            "WHERE subject = :s AND revoked_at IS NULL"
        ),
        {"s": subject},
    )


# ------------------------------------------------- upstream's KeycloakAdmin seam


class LocalAccountAdmin:
    """Upstream's `KeycloakAdmin` Protocol over desktop.account.

    Like the real admin API these are EXTERNAL side effects — each call
    commits on its own session — which is exactly the posture upstream's
    onboarding is written for (look before create, adopt on re-run). A new
    person gets no password: the owner issues them a one-time setup code
    from the People page, since there is no mail server to send a link.
    """

    def __init__(self, sessions: SessionFactory, *, org_alias: str) -> None:
        self._sessions = sessions
        self._org_alias = org_alias

    def find_user_by_email(self, email: str) -> tuple[str, str] | None:
        with self._sessions() as s:
            row = s.execute(
                text("SELECT subject, username FROM desktop.account WHERE lower(email) = lower(:e)"),
                {"e": email},
            ).first()
        return None if row is None else (row[0], row[1])

    def find_user_by_username(self, username: str) -> tuple[str, str] | None:
        with self._sessions() as s:
            row = s.execute(
                text("SELECT subject, coalesce(email, '') FROM desktop.account "
                     "WHERE username = lower(:u)"),
                {"u": username},
            ).first()
        return None if row is None else (row[0], row[1])

    def create_user(
        self, *, username: str, email: str, full_name: str, realm_roles: list[str]
    ) -> str:
        with self._sessions() as s:
            subject = create_account(
                s, username=username, email=email, full_name=full_name, roles=realm_roles
            )
            s.commit()
        return subject

    def assign_realm_roles(self, subject_id: str, realm_roles: list[str]) -> None:
        with self._sessions() as s:
            account = get_account(s, subject_id)
            if account is None:
                raise KeycloakAdminError(f"no local account {subject_id}")
            set_roles(s, subject_id, [*account.roles, *realm_roles])
            s.commit()

    def disable_user(self, subject_id: str) -> None:
        with self._sessions() as s:
            disable(s, subject_id)
            s.commit()

    # One install is one hotel group: organisations collapse to the founding one.
    def find_organization_by_alias(self, alias: str) -> str | None:
        return alias if alias == self._org_alias else None

    def create_organization(self, *, name: str, alias: str) -> str:
        raise KeycloakAdminError("the desktop edition holds one hotel group")

    def add_member(self, org_id: str, subject_id: str) -> None:
        return None

    def set_password(self, subject_id: str, password: str) -> None:
        from usali.desktop.passwords import check_new_password

        check_new_password(password)
        with self._sessions() as s:
            set_password_hash(s, subject_id, hash_secret(password))
            s.commit()
