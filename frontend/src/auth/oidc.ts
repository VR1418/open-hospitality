// OIDC (Authorization Code + PKCE) against the Keycloak `usali` realm.
// Config comes from Vite env so the deployed issuer is a build-time swap:
//   VITE_OIDC_AUTHORITY, VITE_OIDC_CLIENT_ID
//
// Desktop edition (VITE_AUTH_MODE=desktop, docs/desktop/): there is no OIDC
// provider. The launcher's one-time code is traded for a token at
// /desktop-signin, and that token is stored in the SAME oidc-client-ts user
// store — so getUser(), getAccessToken(), authHeaders() and every page keep
// working unchanged. Only login and logout know which mode they are in.
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
    // No provider to redirect to: the sign-in page explains how to open the
    // books from the tray icon, which mints a fresh one-time code.
    window.location.assign(DESKTOP_SIGNIN_PATH)
    return Promise.resolve()
  }
  return loginHint
    ? userManager.signinRedirect({ login_hint: loginHint })
    : userManager.signinRedirect()
}
export async function logout(): Promise<void> {
  if (desktopMode) {
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
