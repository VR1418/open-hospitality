// Desktop edition: night-audit reports that arrive by email
// (src/usali/desktop/mail.py). The owner connects the mailbox their front-desk
// system writes to, says when to look, and allows the senders whose PDFs are
// taken. Reports land in "Drop reports here" and are read like any other.
//
// The password is never shown back; the app only says whether one is saved.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  allowMailSender,
  fetchMailNow,
  forgetMailPassword,
  getMailSettings,
  saveMailSettings,
  testMailConnection,
  type MailSettings,
} from '../api/desktop'
import { Badge, Card, PageHeader, controlClass, sectionHeadClass } from '../components/ui'
import { errorMessage } from '../lib/errors'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const fieldClass = 'flex flex-col gap-1 text-sm'
const labelClass = 'text-xs font-medium text-ink-muted'

function when(iso: string | null): string {
  if (iso === null) return 'never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

type Form = Partial<Omit<MailSettings, 'presets' | 'status' | 'password_saved' | 'senders'>> & {
  password?: string
  senders?: string
}

export default function EmailPage() {
  const queryClient = useQueryClient()
  const mail = useQuery({ queryKey: ['mail'], queryFn: getMailSettings, retry: false })
  const [form, setForm] = useState<Form>({})
  const [saved, setSaved] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['mail'] })

  const settings = mail.data
  const value = <K extends keyof Form>(field: K): Form[K] | undefined =>
    form[field] ?? (settings === undefined || settings === null
      ? undefined
      : field === 'senders'
        ? (settings.senders.join(', ') as Form[K])
        : (settings[field as keyof MailSettings] as Form[K]))
  const set = (patch: Form) => {
    setSaved(false)
    setForm({ ...form, ...patch })
  }

  const save = useMutation({
    mutationFn: () =>
      saveMailSettings({
        enabled: Boolean(value('enabled') ?? false),
        preset: String(value('preset') ?? 'gmail'),
        host: String(value('host') ?? ''),
        port: Number(value('port') ?? 993),
        username: String(value('username') ?? ''),
        folder: String(value('folder') ?? 'INBOX'),
        mode: String(value('mode') ?? 'daily'),
        at: String(value('at') ?? '06:00'),
        every_hours: Number(value('every_hours') ?? 2),
        senders: String(value('senders') ?? '')
          .split(/[,\s;]+/)
          .map((s) => s.trim())
          .filter((s) => s !== ''),
        ...(form.password ? { password: form.password } : {}),
      }),
    onSuccess: () => {
      setForm({})
      setSaved(true)
      void refresh()
    },
  })
  const test = useMutation({ mutationFn: testMailConnection })
  const fetchNow = useMutation({ mutationFn: fetchMailNow, onSettled: () => void refresh() })
  const allow = useMutation({
    mutationFn: (sender: string) => allowMailSender(sender),
    onSettled: () => void refresh(),
  })
  const forget = useMutation({ mutationFn: forgetMailPassword, onSuccess: () => void refresh() })

  if (settings === null) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Reports by email" />
        <Card>
          <p className="text-sm text-ink-muted">This page belongs to the desktop edition.</p>
        </Card>
      </div>
    )
  }
  if (settings === undefined) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Reports by email" />
        <Card>
          {mail.isError ? (
            <p className="text-sm text-danger-red">{errorMessage(mail.error)}</p>
          ) : (
            <p className="text-sm text-ink-muted">Loading…</p>
          )}
        </Card>
      </div>
    )
  }

  const preset = settings.presets.find((p) => p.id === (value('preset') ?? 'gmail'))
  const mode = value('mode') ?? 'daily'
  const status = settings.status

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Reports by email"
        subtitle="If your front-desk system emails the night audit, Open Hospitality can collect it for you"
      />

      <Card>
        <section aria-label="What has come in" className="flex flex-col gap-2">
          <h2 className={sectionHeadClass}>Last look</h2>
          <div className="flex flex-wrap items-center gap-3">
            {settings.enabled ? <Badge tone="ok">On</Badge> : <Badge tone="neutral">Off</Badge>}
            <p className="text-sm text-ink">
              {status.last_run_at === null
                ? 'Hasn’t looked yet.'
                : `${when(status.last_run_at)} — ${status.last_error ?? status.last_result ?? ''}`}
            </p>
            {settings.enabled && status.next_run_at !== null && (
              <p className="text-sm text-ink-muted">Next look {when(status.next_run_at)}.</p>
            )}
            <button
              type="button"
              className={buttonClass}
              disabled={fetchNow.isPending || !settings.password_saved}
              onClick={() => fetchNow.mutate()}
            >
              {fetchNow.isPending ? 'Looking…' : 'Look now'}
            </button>
          </div>
          {status.last_error !== null && (
            <p role="alert" className="text-sm text-danger-red">{status.last_error}</p>
          )}
          {fetchNow.isError && (
            <p role="alert" className="text-sm text-danger-red">{errorMessage(fetchNow.error)}</p>
          )}
          {fetchNow.isSuccess && (
            <p role="status" className="text-sm text-ink">{fetchNow.data.summary}</p>
          )}
          {status.held.length > 0 && (
            <div className="mt-2 rounded-lg border border-warn-amber-soft bg-warn-amber-soft p-3">
              <p className="text-sm font-medium text-ink">
                Reports from senders you haven’t allowed yet — nothing from them is read
                until you do:
              </p>
              <ul className="mt-2 flex flex-col gap-2">
                {status.held.map((h) => (
                  <li key={h.sender} className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="font-medium text-ink">{h.sender}</span>
                    <span className="text-ink-muted">
                      {h.count} email{h.count === 1 ? '' : 's'}
                      {h.subjects.length > 0 && ` · “${h.subjects[0]}”`}
                    </span>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={allow.isPending}
                      onClick={() => allow.mutate(h.sender)}
                    >
                      Allow this sender
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {status.fetched.length > 0 && (
            <p className="text-xs text-ink-muted">
              Collected so far: {status.fetched.slice(0, 5).join(', ')}
              {status.fetched.length > 5 && ` and ${status.fetched.length - 5} more`}. They are
              read from <strong>Drop reports here</strong> like any other report.
            </p>
          )}
        </section>
      </Card>

      <Card>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <section aria-label="The mailbox" className="flex flex-col gap-4">
            <h2 className={sectionHeadClass}>The mailbox</h2>
            <label className={fieldClass} htmlFor="mail-preset">
              <span className={labelClass}>Mail service</span>
              <select
                id="mail-preset"
                aria-label="Mail service"
                className={controlClass}
                value={value('preset') ?? 'gmail'}
                onChange={(e) => set({ preset: e.target.value, host: '', port: 993 })}
              >
                {settings.presets.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              {preset !== undefined && <span className="text-xs text-ink-muted">{preset.hint}</span>}
            </label>
            <div className="flex flex-wrap gap-4">
              <label className={fieldClass} htmlFor="mail-username">
                <span className={labelClass}>Email address the reports are sent to</span>
                <input
                  id="mail-username"
                  className={controlClass}
                  autoComplete="off"
                  value={value('username') ?? ''}
                  onChange={(e) => set({ username: e.target.value })}
                />
              </label>
              <label className={fieldClass} htmlFor="mail-password">
                <span className={labelClass}>
                  Password{settings.password_saved && ' — one is already saved'}
                </span>
                <input
                  id="mail-password"
                  type="password"
                  className={controlClass}
                  autoComplete="new-password"
                  placeholder={settings.password_saved ? 'Leave blank to keep the one saved' : ''}
                  value={form.password ?? ''}
                  onChange={(e) => set({ password: e.target.value })}
                />
                <span className="text-xs text-ink-muted">
                  Kept in this computer’s password store, never in your books or a backup.
                </span>
              </label>
            </div>
            {preset?.id === 'other' && (
              <div className="flex flex-wrap gap-4">
                <label className={fieldClass} htmlFor="mail-host">
                  <span className={labelClass}>IMAP server</span>
                  <input
                    id="mail-host"
                    className={controlClass}
                    placeholder="imap.example.com"
                    value={value('host') ?? ''}
                    onChange={(e) => set({ host: e.target.value })}
                  />
                </label>
                <label className={fieldClass} htmlFor="mail-port">
                  <span className={labelClass}>Port</span>
                  <input
                    id="mail-port"
                    className={controlClass}
                    inputMode="numeric"
                    value={String(value('port') ?? 993)}
                    onChange={(e) => set({ port: Number(e.target.value) || 993 })}
                  />
                </label>
              </div>
            )}
            <label className={fieldClass} htmlFor="mail-folder">
              <span className={labelClass}>Folder to look in</span>
              <input
                id="mail-folder"
                className={controlClass}
                value={value('folder') ?? 'INBOX'}
                onChange={(e) => set({ folder: e.target.value })}
              />
              <span className="text-xs text-ink-muted">
                INBOX unless you file the reports somewhere else.
              </span>
            </label>
            <label className={fieldClass} htmlFor="mail-senders">
              <span className={labelClass}>Take reports only from these senders</span>
              <input
                id="mail-senders"
                className={controlClass}
                placeholder="reports@yourpms.com, audit@hotel.com"
                value={value('senders') ?? ''}
                onChange={(e) => set({ senders: e.target.value })}
              />
              <span className="text-xs text-ink-muted">
                Leave it empty, look once, and allow the right sender from the list above —
                nothing from anyone else is ever read.
              </span>
            </label>
          </section>

          <section aria-label="When to look" className="flex flex-col gap-3">
            <h2 className={sectionHeadClass}>When to look</h2>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={Boolean(value('enabled') ?? false)}
                onChange={(e) => set({ enabled: e.target.checked })}
                aria-label="Collect reports from email"
              />
              <span>Collect reports from this mailbox</span>
            </label>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="mail-mode"
                  checked={mode === 'daily'}
                  onChange={() => set({ mode: 'daily' })}
                />
                <span>Every morning at</span>
                <input
                  type="time"
                  aria-label="Time to look each day"
                  className={controlClass}
                  value={value('at') ?? '06:00'}
                  onChange={(e) => set({ at: e.target.value, mode: 'daily' })}
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="mail-mode"
                  checked={mode === 'every'}
                  onChange={() => set({ mode: 'every' })}
                />
                <span>Every</span>
                <select
                  aria-label="Hours between looks"
                  className={controlClass}
                  value={String(value('every_hours') ?? 2)}
                  onChange={(e) => set({ every_hours: Number(e.target.value), mode: 'every' })}
                >
                  {[1, 2, 3, 4, 6, 8, 12, 24].map((h) => (
                    <option key={h} value={h}>{h} hour{h === 1 ? '' : 's'}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-xs text-ink-muted">
              Night audits usually arrive between 3 and 5 in the morning, so 6 AM catches
              them. Open Hospitality has to be running for a look to happen.
            </p>
          </section>

          {save.isError && (
            <p role="alert" className="text-sm text-danger-red">{errorMessage(save.error)}</p>
          )}
          {saved && <p role="status" className="text-sm text-ink-muted">Saved.</p>}
          {test.isSuccess && (
            <p role="status" className="text-sm text-ink">
              Connected. {test.data.messages_seen} email{test.data.messages_seen === 1 ? '' : 's'} in
              the last {test.data.days} days.
            </p>
          )}
          {test.isError && (
            <p role="alert" className="text-sm text-danger-red">{errorMessage(test.error)}</p>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            {settings.password_saved && Object.keys(form).length === 0 && (
              <button
                type="button"
                className={buttonClass}
                disabled={test.isPending}
                onClick={() => test.mutate()}
              >
                {test.isPending ? 'Checking…' : 'Check it connects'}
              </button>
            )}
            {settings.password_saved && (
              <button
                type="button"
                className={buttonClass}
                disabled={forget.isPending}
                onClick={() => forget.mutate()}
              >
                Forget the password
              </button>
            )}
          </div>
        </form>
      </Card>

      <Card>
        <section aria-label="What it does" className="flex flex-col gap-2">
          <h2 className={sectionHeadClass}>What it does, and doesn’t</h2>
          <p className="text-sm text-ink">
            It opens the mailbox read-only, takes the PDF attachments of new emails from the
            senders you allowed, and puts them in Drop reports here. Nothing is marked read,
            moved or deleted.
          </p>
          <p className="text-sm text-ink-muted">
            It never reads the text of an email, never follows a link in one, and never shows
            an email to the AI helper. Which hotel a report belongs to comes from the report
            itself.
          </p>
        </section>
      </Card>
    </div>
  )
}
