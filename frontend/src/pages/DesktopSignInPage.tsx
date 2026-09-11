// Desktop edition front door (PRD 6.2, docs/desktop/). One page, five screens:
//
//   first run   the tray icon opens /desktop-signin#code=<one-time code>; the
//               code lets THIS browser create the owner, and nothing else
//   sign in     email and password
//   set-up code a person the owner added sets their password
//   recover     the owner's recovery code → a new password and a new code
//   saved?      a recovery code is shown once, with the one warning that matters
//
// The launch code travels in the URL fragment, which the browser never sends
// anywhere, and is scrubbed from history on arrival. Every refusal shown here
// is the server's own sentence, which names the next step.
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react'

import {
  getSetupRequired,
  recover,
  redeemSetupCode,
  setUpOwner,
  signIn,
  type DesktopToken,
} from '../api/desktop'
import { getUser, storeDesktopSession } from '../auth/oidc'
import { Card, controlLargeClass } from '../components/ui'

type Screen =
  | { kind: 'loading' }
  | { kind: 'unreachable' }
  | { kind: 'no-launch-code' }
  | { kind: 'owner-setup'; code: string }
  | { kind: 'sign-in' }
  | { kind: 'setup-code' }
  | { kind: 'recover' }
  | { kind: 'recovery-code'; code: string; replaced: boolean }

function takeCode(): string | null {
  const code = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('code')
  if (window.location.hash) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return code
}

function openBooks() {
  window.location.replace('/')
}

const HOW_TO_OPEN =
  'Click the Open Hospitality icon in your menu bar (Mac) or system tray (Windows) and ' +
  'choose “Open my books”.'

const PASSWORD_HINT =
  'At least 10 characters. A few unrelated words make a strong password that’s easy to remember.'

const primaryButtonClass =
  'h-11 w-full rounded-lg bg-accent px-5 text-sm font-semibold text-accent-contrast shadow-sm ' +
  'transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const linkButtonClass = 'text-sm font-medium text-accent underline-offset-2 hover:underline'

export default function DesktopSignInPage() {
  const [screen, setScreen] = useState<Screen>({ kind: 'loading' })
  const [signedOut, setSignedOut] = useState(false)
  // The launch code must be read once: React's development double-effect
  // would otherwise scrub it on the first pass and find nothing on the second.
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const code = takeCode()
    const wasSignedOut = new URLSearchParams(window.location.search).has('signed-out')
    setSignedOut(wasSignedOut)
    void (async () => {
      // Already signed in on this browser (the tray's "Open my books" after a
      // first sign-in): straight to the books. A token the server has since
      // refused is removed by login() before it sends anyone here.
      const user = await getUser().catch(() => null)
      if (user !== null && !user.expired && !wasSignedOut) {
        openBooks()
        return
      }
      let setupRequired: boolean
      try {
        setupRequired = await getSetupRequired()
      } catch {
        setScreen({ kind: 'unreachable' })
        return
      }
      if (!setupRequired) setScreen({ kind: 'sign-in' })
      else setScreen(code === null ? { kind: 'no-launch-code' } : { kind: 'owner-setup', code })
    })()
  }, [])

  /** Keep the session, then either show the new recovery code or go in. */
  async function signedInWith(token: DesktopToken, replaced: boolean) {
    await storeDesktopSession(token.access_token, token.expires_in)
    if (token.recovery_code !== null && token.recovery_code !== undefined) {
      setScreen({ kind: 'recovery-code', code: token.recovery_code, replaced })
    } else {
      openBooks()
    }
  }

  switch (screen.kind) {
    case 'loading':
      return (
        <Shell>
          <p className="text-sm text-ink-muted">Opening your books…</p>
        </Shell>
      )
    case 'unreachable':
      return (
        <Shell title="Open Hospitality isn’t answering">
          <p className="text-sm text-ink-muted">
            It may still be starting, or it may have been closed. {HOW_TO_OPEN}
          </p>
        </Shell>
      )
    case 'no-launch-code':
      return (
        <Shell title="Welcome to Open Hospitality">
          <p className="text-sm text-ink-muted">
            To set up your books, open this page from Open Hospitality itself. {HOW_TO_OPEN}
          </p>
        </Shell>
      )
    case 'owner-setup':
      return (
        <OwnerSetupForm
          launchCode={screen.code}
          onDone={(token) => signedInWith(token, false)}
        />
      )
    case 'sign-in':
      return (
        <SignInForm
          signedOut={signedOut}
          onDone={(token) => signedInWith(token, false)}
          onSetupCode={() => setScreen({ kind: 'setup-code' })}
          onRecover={() => setScreen({ kind: 'recover' })}
        />
      )
    case 'setup-code':
      return (
        <SetupCodeForm
          onDone={(token) => signedInWith(token, false)}
          onBack={() => setScreen({ kind: 'sign-in' })}
        />
      )
    case 'recover':
      return (
        <RecoverForm
          onDone={(token) => signedInWith(token, true)}
          onBack={() => setScreen({ kind: 'sign-in' })}
        />
      )
    case 'recovery-code':
      return <RecoveryCodeScreen code={screen.code} replaced={screen.replaced} />
  }
}

// --- pieces -----------------------------------------------------------------

function Shell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-10">
      <p className="mb-6 text-lg font-semibold tracking-tight">
        <span aria-hidden="true" className="text-accent">
          ◆
        </span>{' '}
        <span className="text-accent">Open</span> Hospitality
      </p>
      <Card>
        {title !== undefined && <h1 className="mb-3 text-xl font-semibold text-ink">{title}</h1>}
        {children}
      </Card>
    </main>
  )
}

function Field({
  label,
  hint,
  ...input
}: {
  label: string
  hint?: string
} & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-ink-muted">{label}</span>
      <input aria-label={label} className={controlLargeClass} required {...input} />
      {hint !== undefined && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  )
}

function Refusal({ message }: { message: string | null }) {
  if (message === null) return null
  return (
    <p role="alert" className="text-sm text-danger-red">
      {message}
    </p>
  )
}

/** Runs a submit: one at a time, the server's refusal kept for display. */
function useSubmit() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function run(event: FormEvent, action: () => Promise<void>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }
  return { busy, error, setError, run }
}

const MISMATCH = 'The two passwords don’t match. Type the same password in both boxes.'

function OwnerSetupForm({
  launchCode,
  onDone,
}: {
  launchCode: string
  onDone: (token: DesktopToken) => Promise<void>
}) {
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const { busy, error, setError, run } = useSubmit()

  return (
    <Shell title="Set up your books">
      <p className="mb-5 text-sm text-ink-muted">
        You’re the owner of this copy of Open Hospitality. You can add the people who work with
        you later.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) =>
          run(e, async () => {
            if (password !== confirm) {
              setError(MISMATCH)
              throw new Error(MISMATCH)
            }
            await onDone(
              await setUpOwner({ code: launchCode, full_name: fullName, email, password }),
            )
          })
        }
      >
        <Field
          label="Your full name"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          hint="You’ll sign in with this. Nothing is sent to it."
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label="Type the password again"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Refusal message={error} />
        <button type="submit" className={primaryButtonClass} disabled={busy}>
          {busy ? 'Setting up…' : 'Set up my books'}
        </button>
      </form>
    </Shell>
  )
}

function SignInForm({
  signedOut,
  onDone,
  onSetupCode,
  onRecover,
}: {
  signedOut: boolean
  onDone: (token: DesktopToken) => Promise<void>
  onSetupCode: () => void
  onRecover: () => void
}) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, run } = useSubmit()

  return (
    <Shell title="Sign in">
      {signedOut && (
        <p role="status" className="mb-4 text-sm text-ink-muted">
          You’re signed out.
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => run(e, async () => onDone(await signIn({ login, password })))}
      >
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Refusal message={error} />
        <button type="submit" className={primaryButtonClass} disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <div className="mt-5 flex flex-col items-start gap-2 border-t border-line pt-4">
        <button type="button" className={linkButtonClass} onClick={onRecover}>
          Forgot your password? Use your recovery code
        </button>
        <button type="button" className={linkButtonClass} onClick={onSetupCode}>
          Have a set-up code from the owner?
        </button>
      </div>
    </Shell>
  )
}

function SetupCodeForm({
  onDone,
  onBack,
}: {
  onDone: (token: DesktopToken) => Promise<void>
  onBack: () => void
}) {
  const [login, setLogin] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const { busy, error, setError, run } = useSubmit()

  return (
    <Shell title="Choose your password">
      <p className="mb-5 text-sm text-ink-muted">
        Use the set-up code the owner gave you. It works once, for 24 hours.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) =>
          run(e, async () => {
            if (password !== confirm) {
              setError(MISMATCH)
              throw new Error(MISMATCH)
            }
            await onDone(await redeemSetupCode({ login, code, new_password: password }))
          })
        }
      >
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
        />
        <Field
          label="Set-up code"
          autoComplete="one-time-code"
          placeholder="XXXX-XXXX"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label="Type the password again"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Refusal message={error} />
        <button type="submit" className={primaryButtonClass} disabled={busy}>
          {busy ? 'Saving…' : 'Save my password'}
        </button>
      </form>
      <button type="button" className={`${linkButtonClass} mt-4`} onClick={onBack}>
        Back to sign in
      </button>
    </Shell>
  )
}

function RecoverForm({
  onDone,
  onBack,
}: {
  onDone: (token: DesktopToken) => Promise<void>
  onBack: () => void
}) {
  const [login, setLogin] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const { busy, error, setError, run } = useSubmit()

  return (
    <Shell title="Use your recovery code">
      <p className="mb-5 text-sm text-ink-muted">
        This is the code you saved when you set up Open Hospitality. Using it signs you out
        everywhere else and gives you a new code.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) =>
          run(e, async () => {
            if (password !== confirm) {
              setError(MISMATCH)
              throw new Error(MISMATCH)
            }
            await onDone(await recover({ login, recovery_code: code, new_password: password }))
          })
        }
      >
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          value={login}
          onChange={(e) => setLogin(e.target.value)}
        />
        <Field
          label="Recovery code"
          autoComplete="off"
          spellCheck={false}
          hint="Dashes and capital letters don’t matter."
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label="Type the password again"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <Refusal message={error} />
        <button type="submit" className={primaryButtonClass} disabled={busy}>
          {busy ? 'Saving…' : 'Set my new password'}
        </button>
      </form>
      <button type="button" className={`${linkButtonClass} mt-4`} onClick={onBack}>
        Back to sign in
      </button>
    </Shell>
  )
}

/** PRD A-6: the warning is stated once, plainly, at the moment it matters. */
function RecoveryCodeScreen({ code, replaced }: { code: string; replaced: boolean }) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  return (
    <Shell title={replaced ? 'Your new recovery code' : 'Save your recovery code'}>
      {replaced && (
        <p className="mb-3 text-sm text-ink-muted">
          Your password is changed. The recovery code you just used no longer works — this one
          replaces it.
        </p>
      )}
      <p
        aria-label="Recovery code"
        className="my-4 select-all rounded-lg border border-line bg-surface-sunken px-4 py-3 text-center font-mono text-lg tracking-wider text-ink"
      >
        {code}
      </p>
      <div className="mb-4 flex gap-2 print:hidden">
        <button
          type="button"
          className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken"
          onClick={() => {
            void navigator.clipboard
              ?.writeText(code)
              .then(() => setCopied(true))
              .catch(() => {})
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken"
          onClick={() => window.print()}
        >
          Print
        </button>
      </div>
      <p className="text-sm text-ink">
        If you forget your password, this code is the only way back in. There is no reset email.{' '}
        <strong>
          If you lose both your password and this code, nobody — not even us — can open your
          books.
        </strong>
      </p>
      <p className="mt-2 text-sm text-ink-muted">
        Write it down or print it, and keep it somewhere safe that isn’t this computer.
      </p>
      <label className="mt-5 flex items-start gap-2 text-sm text-ink print:hidden">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
        />
        I’ve saved my recovery code somewhere safe
      </label>
      <button
        type="button"
        className={`${primaryButtonClass} mt-4 print:hidden`}
        disabled={!saved}
        onClick={openBooks}
      >
        Open my books
      </button>
    </Shell>
  )
}
