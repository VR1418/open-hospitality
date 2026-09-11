# ADR-D1: Local single-owner token issuer replacing Keycloak on the desktop

- **Status:** Proposed
- **Date:** 2026-09-11
- **Deciders:** desktop-edition owner *(to be named)*; drafted with Claude

## Context

Upstream authenticates every operator request with an RS256 JWT from a Keycloak
realm (ADR-003). `auth.TokenVerifier` checks issuer, audience, expiry and
signature. It turns claims into a `Principal` (roles from `realm_access`, org
**aliases** from `organization`), and `require_active_org` resolves the alias to
an `org_id` through the database. Authority is the `role_assignment` grants that
row-level security leaves visible.

A desktop install has one owner, no server and no JVM. Keycloak is a
multi-tenant federation server, and bundling it would add a Java runtime and a
second database to a product that has to install with one double-click
(PRD 6.1). Leaving the API unauthenticated because it only listens on
localhost doesn't work either: any web page can reach `127.0.0.1` via DNS
rebinding, and so can every other process and user on the machine.

## Decision

We will **sign tokens locally and leave verification untouched**.

- On first run the desktop edition generates an RSA-3072 keypair.
  `usali.desktop.identity.LocalIssuer` mints RS256 tokens with exactly the
  claims the dev realm emits:
  - `iss`, `aud=usali-api`, `sub` and `exp` (8 hours)
  - `realm_access.roles`
  - `organization: [<alias>]`
- The engine receives upstream's own `TokenVerifier`, pointed at the local
  public key through `create_app(token_verifier=…)`, the seam the test suite
  already uses. No verifier code, role check, org resolution or RLS policy
  changes.
- **M1:** there are no accounts yet. The launcher mints a random one-time code
  (two-minute TTL, stored only as a hash) and opens the browser at
  `/desktop-signin#code=…`. The page exchanges it at `POST /api/desktop/session`.
  The code rides in the URL fragment, which the browser never sends to a server
  or includes in a Referer.
- **Every request** must carry a loopback `Host` (`TrustedHostMiddleware`),
  which defeats DNS rebinding. No CORS headers are sent.
- **M2** replaces the launch code with the owner's account:
  - Argon2id password with a breached-list check, plus a recovery code
    (PRD A-1 to A-3, A-6).
  - Per-device sessions (A-7).
  - The signing key moves from the key file into the OS keychain (A-4).

  The issuer, the token and everything downstream stay as they are.
- The owner's identity is `sub=desktop-owner`, holding an org-wide `org_admin`
  grant in the founding org. Roles keep upstream's meaning (A-8).

## Consequences

- Upstream's authorization model, its tests and every future change to it apply
  to the desktop edition unmodified. That's the point of "do not fork the
  engine".
- The frontend gains a small desktop auth mode (`VITE_AUTH_MODE=desktop`) that
  writes the token into the same `oidc-client-ts` user store. Pages,
  `authHeaders()` and org resolution are unchanged.
- Anyone who can run the launcher as the owner's OS user can open the books in
  M1. That is the same trust as the owner's files on disk, and M2's password
  narrows it.
- **Until M2 the signing key sits in `keys.json`** in the per-user app-data
  folder (owner-only permissions on POSIX), next to the database passwords, the
  field-encryption key and the HPKE key. Losing that file makes the database
  unopenable. M3's backup must carry it, encrypted.
- Operator onboarding still calls upstream's Keycloak admin client, so adding a
  second operator fails loudly in M1. M2 supplies a local implementation of the
  `KeycloakAdmin` seam.
- There is no refresh token. An expired session goes back through the tray icon
  (M1) or the sign-in screen (M2), never a silent renewal.

## Alternatives considered

- **Bundle Keycloak.** It needs a JVM, adds about 200 MB and a second
  database, and solves federation the desktop doesn't have. Rejected in the PRD.
- **No authentication on localhost.** DNS rebinding lets any web page read
  responses. Every local process and user gets the books.
- **HS256 with a shared secret.** The verifier accepts RS256 only; allowing HS
  reopens algorithm-confusion attacks upstream deliberately closed.
- **A minimal local OIDC provider** (discovery, authorize, token, JWKS), so
  `oidc-client-ts` runs unchanged. It's more code and more attack surface for
  the same trust result. It could return if the SPA's OIDC path ever becomes
  the only one worth keeping.
- **A long-lived static token baked into the build.** It would be identical
  for every install, never expire, and could be copied off any machine.
