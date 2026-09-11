// Desktop edition: "Sign-in & security" (PRD A-7). Everyone sees their own
// sign-ins, per device, with individual sign-out, and can change their
// password. The owner also sees everyone who can sign in and can hand any of
// them a one-time set-up code — how a new person gets their first password,
// and how a forgotten one is reset (there is no reset email).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { getMe } from '../api/client'
import {
  changePassword,
  getAccounts,
  getSessions,
  giveSetupCode,
  signOutDevice,
  type DesktopAccount,
  type DesktopSession,
  type SetupCode,
} from '../api/desktop'
import { useAuth } from '../auth/authContext'
import {
  Badge,
  Card,
  PageHeader,
  cellClass,
  controlLargeClass,
  headCellClass,
  sectionHeadClass,
  tableClass,
} from '../components/ui'
import { errorMessage } from '../lib/errors'
import { hasRole } from '../lib/roles'

const buttonClass =
  'shrink-0 rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

const ROLE_WORDS: Record<string, string> = {
  org_admin: 'Owner',
  accountant: 'Bookkeeper',
  property_gm: 'Hotel manager',
  department_manager: 'Department head',
  payroll_admin: 'Payroll manager',
}

function roleWords(roles: string[]): string {
  const words = roles.map((r) => ROLE_WORDS[r]).filter((w) => w !== undefined)
  return words.length > 0 ? words.join(', ') : 'Staff'
}

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function AccountPage() {
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  const isOwner = hasRole(me.data, 'org_admin')

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Sign-in and security"
        subtitle="Where you’re signed in, your password, and who else can sign in."
      />
      <SessionsCard />
      <PasswordCard />
      {isOwner && <PeopleCard />}
    </div>
  )
}

function SessionsCard() {
  const queryClient = useQueryClient()
  const { logout } = useAuth()
  const sessions = useQuery({ queryKey: ['desktop-sessions'], queryFn: getSessions })
  const end = useMutation({
    mutationFn: (id: string) => signOutDevice(id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['desktop-sessions'] }),
  })

  function signOut(s: DesktopSession) {
    if (s.current) logout()
    else end.mutate(s.session_id)
  }

  return (
    <Card role="region" aria-label="Your sign-ins">
      <h2 className="text-base font-semibold text-ink">Your sign-ins</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Each browser you’ve signed in from. If you don’t recognise one, sign it out and change
        your password.
      </p>
      {sessions.isPending && <p className="mt-3 text-sm text-ink-muted">Loading …</p>}
      {sessions.isError && (
        <p className="mt-3 text-sm text-danger-red">
          Couldn’t load your sign-ins: {errorMessage(sessions.error)}
        </p>
      )}
      {end.isError && (
        <p role="alert" className="mt-3 text-sm text-danger-red">
          {errorMessage(end.error)}
        </p>
      )}
      {sessions.data !== undefined && (
        <div className="mt-3 overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={headCellClass}>Device</th>
                <th className={headCellClass}>Signed in</th>
                <th className={headCellClass}>Last used</th>
                <th className={headCellClass}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sessions.data.map((s) => (
                <tr key={s.session_id} className="border-t border-line">
                  <td className={cellClass}>
                    <span className="flex flex-wrap items-center gap-2">
                      {s.device_label || 'A browser'}
                      {s.current && <Badge tone="ok">This device</Badge>}
                    </span>
                  </td>
                  <td className={cellClass}>{when(s.created_at)}</td>
                  <td className={cellClass}>{when(s.last_seen_at)}</td>
                  <td className={`${cellClass} text-right`}>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={end.isPending}
                      aria-label={
                        s.current
                          ? 'Sign out of this device'
                          : `Sign out ${s.device_label || 'this browser'}`
                      }
                      onClick={() => signOut(s)}
                    >
                      Sign out
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function PasswordCard() {
  const queryClient = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [mismatch, setMismatch] = useState(false)
  const change = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setConfirm('')
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['desktop-sessions'] }),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    setMismatch(next !== confirm)
    if (next === confirm) change.mutate()
  }

  return (
    <Card role="region" aria-label="Change your password">
      <h2 className="text-base font-semibold text-ink">Change your password</h2>
      <p className="mt-1 text-sm text-ink-muted">
        This signs you out everywhere except here. At least 10 characters — a few unrelated words
        work well.
      </p>
      <form className="mt-4 flex max-w-sm flex-col gap-3" onSubmit={submit}>
        <PasswordField label="Current password" value={current} onChange={setCurrent} current />
        <PasswordField label="New password" value={next} onChange={setNext} />
        <PasswordField label="Type the new password again" value={confirm} onChange={setConfirm} />
        {mismatch && (
          <p role="alert" className="text-sm text-danger-red">
            The two new passwords don’t match.
          </p>
        )}
        {change.isError && (
          <p role="alert" className="text-sm text-danger-red">
            {errorMessage(change.error)}
          </p>
        )}
        {change.isSuccess && (
          <p role="status" className="text-sm text-ink-muted">
            Your password is changed.
          </p>
        )}
        <div>
          <button type="submit" className={primaryButtonClass} disabled={change.isPending}>
            {change.isPending ? 'Saving…' : 'Change password'}
          </button>
        </div>
      </form>
    </Card>
  )
}

function PasswordField({
  label,
  value,
  onChange,
  current = false,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  current?: boolean
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-ink-muted">{label}</span>
      <input
        aria-label={label}
        type="password"
        required
        autoComplete={current ? 'current-password' : 'new-password'}
        className={controlLargeClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function PeopleCard() {
  const accounts = useQuery({ queryKey: ['desktop-accounts'], queryFn: getAccounts })
  const [issued, setIssued] = useState<{ person: DesktopAccount; code: SetupCode } | null>(null)
  const give = useMutation({
    mutationFn: async (person: DesktopAccount) => ({ person, code: await giveSetupCode(person.subject) }),
    onSuccess: (result) => setIssued(result),
  })

  return (
    <Card role="region" aria-label="People who can sign in">
      <h2 className="text-base font-semibold text-ink">People who can sign in</h2>
      <p className="mt-1 text-sm text-ink-muted">
        To add someone, turn on Payroll &amp; People on the Modules page, then add them on the
        Employees page with a role that signs in. Give them a set-up code here; they choose
        “Have a set-up code from the owner?” on the sign-in screen. A new code also resets a
        forgotten password.
      </p>
      {accounts.isPending && <p className="mt-3 text-sm text-ink-muted">Loading …</p>}
      {accounts.isError && (
        <p className="mt-3 text-sm text-danger-red">
          Couldn’t load the people who can sign in: {errorMessage(accounts.error)}
        </p>
      )}
      {give.isError && (
        <p role="alert" className="mt-3 text-sm text-danger-red">
          {errorMessage(give.error)}
        </p>
      )}
      {issued !== null && (
        <div role="status" className="mt-4 rounded-lg border border-line bg-surface-sunken p-4">
          <p className={sectionHeadClass}>Set-up code for {issued.person.full_name}</p>
          <p className="mt-2 select-all font-mono text-2xl tracking-widest text-ink">
            {issued.code.setup_code}
          </p>
          <p className="mt-2 text-sm text-ink-muted">
            Give this to {issued.person.full_name} in person or by phone. It works once, for{' '}
            {issued.code.valid_for_hours} hours, with the email {issued.person.email ?? issued.person.username}.
            It won’t be shown again — if it’s lost, make a new one.
          </p>
        </div>
      )}
      {accounts.data !== undefined && (
        <div className="mt-3 overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={headCellClass}>Name</th>
                <th className={headCellClass}>Email</th>
                <th className={headCellClass}>Role</th>
                <th className={headCellClass}>Status</th>
                <th className={headCellClass}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {accounts.data.map((a) => (
                <tr key={a.subject} className="border-t border-line">
                  <td className={cellClass}>{a.full_name}</td>
                  <td className={cellClass}>{a.email ?? a.username}</td>
                  <td className={cellClass}>{a.is_owner ? 'Owner' : roleWords(a.roles)}</td>
                  <td className={cellClass}>
                    {!a.enabled ? (
                      <Badge tone="neutral">Can’t sign in</Badge>
                    ) : a.has_password ? (
                      <Badge tone="ok">Active</Badge>
                    ) : (
                      <Badge tone="warn">Needs a set-up code</Badge>
                    )}
                  </td>
                  <td className={`${cellClass} text-right`}>
                    {!a.is_owner && a.enabled && (
                      <button
                        type="button"
                        className={buttonClass}
                        disabled={give.isPending}
                        aria-label={`Give ${a.full_name} a set-up code`}
                        onClick={() => give.mutate(a)}
                      >
                        {a.has_password ? 'Reset password' : 'Give set-up code'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
