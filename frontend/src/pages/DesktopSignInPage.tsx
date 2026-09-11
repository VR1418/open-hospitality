// Desktop edition sign-in (docs/desktop/). The tray icon opens the browser at
// /desktop-signin#code=<one-time code>; this page trades the code for a
// session and goes to the books. The code travels in the URL fragment, which
// the browser never sends anywhere, and is scrubbed from history on arrival.
import { useEffect, useRef, useState } from 'react'

import { storeDesktopSession } from '../auth/oidc'

type State =
  | { kind: 'working' }
  | { kind: 'no-code'; signedOut: boolean }
  | { kind: 'refused'; message: string }

function takeCode(): string | null {
  const code = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('code')
  if (window.location.hash) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return code
}

const HOW_TO_OPEN =
  'To open your books, click the Open Hospitality icon in your menu bar (Mac) or ' +
  'system tray (Windows) and choose “Open my books”.'

export default function DesktopSignInPage() {
  const [state, setState] = useState<State>({ kind: 'working' })
  // A one-time code must be spent once: React's development double-effect
  // would otherwise try the same code twice and show the second refusal.
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const code = takeCode()
    if (!code) {
      const signedOut = new URLSearchParams(window.location.search).has('signed-out')
      setState({ kind: 'no-code', signedOut })
      return
    }
    fetch('/api/desktop/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
      .then(async (res) => {
        const body: unknown = await res.json().catch(() => ({}))
        const record = (body ?? {}) as Record<string, unknown>
        if (!res.ok) {
          throw new Error(typeof record.detail === 'string' ? record.detail : HOW_TO_OPEN)
        }
        await storeDesktopSession(String(record.access_token), Number(record.expires_in))
        window.location.replace('/')
      })
      .catch((err: unknown) => {
        setState({ kind: 'refused', message: err instanceof Error ? err.message : HOW_TO_OPEN })
      })
  }, [])

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="mb-4 text-xl font-semibold">Open Hospitality</h1>
      {state.kind === 'working' && <p className="text-ink-muted">Opening your books…</p>}
      {state.kind === 'no-code' && (
        <p className="text-ink-muted">
          {state.signedOut ? 'You’re signed out. ' : ''}
          {HOW_TO_OPEN}
        </p>
      )}
      {state.kind === 'refused' && (
        <p role="alert" className="text-ink-muted">
          {state.message}
        </p>
      )}
    </main>
  )
}
