"""The desktop edition's token issuer (ADR-D1): Keycloak's job, done locally.

Upstream verifies RS256 JWTs from a Keycloak realm. A single-owner desktop
install has no realm, so this module SIGNS the tokens instead — with a
keypair generated on first run — and hands the engine upstream's own
`TokenVerifier`, pointed at the local public key. The verifier, every role
check and the org-alias resolution are untouched: this is a swap at the
issuer boundary only (PRD A-4).

The claims mirror what the dev realm emits, because that is the contract
`auth._principal_from_claims` enforces: `realm_access.roles` for the coarse
operator door, `organization` as a JSON array of org ALIASES (never ids),
`sub` as the subject `role_assignment` grants are keyed on.
"""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from usali.auth import AuthError, Principal, TokenVerifier

ISSUER = "urn:open-hospitality:desktop"
# Must equal Settings.oidc_audience's default: the claim the resource server
# requires. The desktop never overrides that setting.
AUDIENCE = "usali-api"
# Short-lived (A-4). An expired session sends the owner back through the
# launcher (M1) or the sign-in screen (M2) — never a silent refresh.
DEFAULT_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class DesktopUser:
    subject: str
    username: str
    roles: tuple[str, ...]
    org_alias: str


class LocalIssuer:
    def __init__(
        self,
        private_key: rsa.RSAPrivateKey,
        *,
        issuer: str = ISSUER,
        audience: str = AUDIENCE,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._key = private_key
        self._public = private_key.public_key()
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl_seconds
        spki = self._public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        # The kid names THIS key, so a token signed by a replaced key (a
        # restored backup from another install, say) fails on kid before it
        # ever reaches a signature check.
        self.kid = hashlib.sha256(spki).hexdigest()[:16]

    @staticmethod
    def generate_pem() -> str:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    @classmethod
    def from_pem(cls, pem: str, **kwargs: int | str) -> "LocalIssuer":
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("the desktop signing key is not an RSA private key")
        return cls(key, **kwargs)  # type: ignore[arg-type]  # keyword pass-through

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def mint(
        self, user: DesktopUser, *, now: int | None = None, session_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        issued = int(time.time()) if now is None else now
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        claims: dict[str, object] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": user.subject,
            "preferred_username": user.username,
            "iat": issued,
            "nbf": issued,
            "exp": issued + ttl,
            "realm_access": {"roles": list(user.roles)},
            "organization": [user.org_alias],
        }
        if session_id is not None:
            claims["sid"] = session_id
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.kid})

    def _resolver(self) -> Callable[[str], object]:
        public = self._public
        kid = self.kid

        def resolve(requested: str) -> object:
            if requested != kid:
                raise KeyError(requested)  # the verifier's injected-resolver contract
            return public

        return resolve

    def verifier(
        self, *, session_is_live: Callable[[str, str], bool] | None = None
    ) -> TokenVerifier:
        """Upstream's verifier over the local key. With `session_is_live`,
        also refuse a token whose sign-in session has ended (A-7)."""
        if session_is_live is None:
            return TokenVerifier(
                issuer=self._issuer, audience=self._audience,
                signing_key_resolver=self._resolver(),
            )
        return SessionCheckedVerifier(
            issuer=self._issuer, audience=self._audience,
            signing_key_resolver=self._resolver(), session_is_live=session_is_live,
        )


class SessionCheckedVerifier(TokenVerifier):
    """Upstream's `TokenVerifier`, unchanged, plus ONE desktop rule: the
    token's `sid` must name a sign-in session that is still live. That is
    what makes "sign out that device" (PRD A-7) and disabling a person take
    effect at once, rather than when their token happens to expire."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        signing_key_resolver: Callable[[str], object],
        session_is_live: Callable[[str, str], bool],
    ) -> None:
        super().__init__(
            issuer=issuer, audience=audience, signing_key_resolver=signing_key_resolver
        )
        self._session_is_live = session_is_live

    def verify(self, token: str) -> Principal:
        principal = super().verify(token)  # signature, issuer, audience, expiry
        # Already verified above; this second read only fetches the sid.
        sid = jwt.decode(token, options={"verify_signature": False}).get("sid")
        if not isinstance(sid, str) or not self._session_is_live(sid, principal.subject):
            raise AuthError("sign-in session has ended")
        return principal
