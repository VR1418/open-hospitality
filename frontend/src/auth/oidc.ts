// OIDC (Authorization Code + PKCE) against the Keycloak `usali` realm.
// Config comes from Vite env so the deployed issuer is a build-time swap:
//   VITE_OIDC_AUTHORITY, VITE_OIDC_CLIENT_ID
//
// Desktop edition (VITE_AUTH_MODE=desktop, docs/desktop/): there is no OIDC
// provider. /desktop-signin trades an email and password (or, on first run,
// the new owner's details) for a locally minted token, stored in the SAME
// oidc-client-ts user store — so getUser(), getAccessToken(), authHeaders()
// and every page keep working unchanged. Only login and logout know which
// mode they are in.
import { User, UserManager, WebStorageStateStore, type UserProfile } from 'oidc-client-ts'

export const desktopMode = import.meta.env.VITE_AUTH_MODE === 'desktop'
export const DESKTOP_SIGNIN_PATH = '/desktop-signin'

const authority =
  import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:9080/realms/usali'
const client_id = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'operator-portal'

// KNOWN LIMITATION (A1): no automatic token refresh. automaticSilentRenew and
// monitorSession default to false, and scope 'openid profile' omits
// offline_access — so Keycloak issues no refresh token and sessions simply
// expire. When silent renew is enabled later, add offline_access (or use
// prompt=none via the session iframe) and turn on automaticSilentRenew.
export const userManager = new UserManager({
  authority,
  client_id,
  redirect_uri: `${window.location.origin}/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: 'code',
  scope: 'openid profile',
  userStore: new WebStorageStateStore({ store: window.localStorage }),
})

export function login(loginHint?: string): Promise<void> {
  if (desktopMode) {
    // No provider to redirect to: the sign-in page asks for a password. A
    // stored token the server just refused (this device was signed out from
    // another one, or the session ran out) goes first — otherwise the sign-in
    // page would forward straight back to it.
    return userManager.removeUser().then(() => {
      window.location.assign(DESKTOP_SIGNIN_PATH)
    })
  }
  return loginHint
    ? userManager.signinRedirect({ login_hint: loginHint })
    : userManager.signinRedirect()
}
export async function logout(): Promise<void> {
  if (desktopMode) {
    // End the session on the server too, so this token dies now rather than
    // at expiry. Best effort: signing out of this browser must never fail.
    // Imported lazily because client.ts imports this module.
    try {
      const { authHeaders } = await import('../api/client')
      await fetch('/api/desktop/signout', { method: 'POST', headers: await authHeaders() })
    } catch {
      // Offline or already ended: the local sign-out below still happens.
    }
    await userManager.removeUser()
    window.location.assign(`${DESKTOP_SIGNIN_PATH}?signed-out=1`)
    return
  }
  return userManager.signoutRedirect()
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const part = token.split('.')[1] ?? ''
  const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
  const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0))
  return JSON.parse(new TextDecoder().decode(bytes)) as Record<string, unknown>
}

/** Store a desktop session token where every consumer already looks. The
 * profile is read, not verified — the server verifies every request. */
export async function storeDesktopSession(accessToken: string, expiresIn: number): Promise<void> {
  const user = new User({
    access_token: accessToken,
    token_type: 'Bearer',
    profile: decodeJwtPayload(accessToken) as UserProfile,
    expires_at: Math.floor(Date.now() / 1000) + expiresIn,
  })
  await userManager.storeUser(user)
}
export function getUser(): Promise<User | null> {
  return userManager.getUser()
}
export async function getAccessToken(): Promise<string | null> {
  const u = await userManager.getUser()
  return u && !u.expired ? u.access_token : null
}
