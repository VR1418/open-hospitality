// Desktop edition first-run wizard (PRD M2): hotel group → first hotel →
// fiscal year → where backups go (PRD I-6) → modules. The owner is sent here after their first sign-in,
// and after every launch until it is finished (Layout does the sending).
//
// What a real owner needs before their first report can become a statement:
// a property the report's header resolves to, its rooms, and a fiscal
// calendar — without the calendar, reports are read but nothing posts to the
// ledger, so the statement stays empty. The hotel and its fiscal year are
// saved in ONE request at the end of step 3, so there is never a half-made
// hotel to resume from; the group name is saved as soon as it is given.
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import {
  addHotel,
  finishWelcome,
  getBackupStatus,
  getModules,
  getWelcome,
  nameGroup,
  setBackupFolder,
  saveModules,
  waitForModules,
  type DesktopModule,
  type FiscalChoice,
  type WelcomeState,
} from '../api/desktop'
import { Card, controlLargeClass, sectionHeadClass } from '../components/ui'
import { errorMessage } from '../lib/errors'

type Step = 'group' | 'hotel' | 'fiscal' | 'backup' | 'modules' | 'done'
const STEP_NUMBER: Record<Exclude<Step, 'done'>, number> = {
  group: 1,
  hotel: 2,
  fiscal: 3,
  backup: 4,
  modules: 5,
}

type HotelDraft = {
  ownership_entity: string
  name: string
  code: string
  report_name: string
  pms_source: string
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
// Python's weekday(): 0 is Monday (src/usali/fiscal.py).
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const primaryButtonClass =
  'h-11 rounded-lg bg-accent px-5 text-sm font-semibold text-accent-contrast shadow-sm ' +
  'transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const secondaryButtonClass =
  'h-11 rounded-lg border border-line px-5 text-sm font-medium text-ink hover:bg-surface-sunken ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

/** Where a returning owner picks up: the first question not yet answered. */
function firstStep(w: WelcomeState): Step {
  if (!w.group_named) return 'group'
  if (w.properties.length === 0) return 'hotel'
  // PRD I-6: a copy of the books is part of setting up, not a settings page.
  if (!w.backup_folder_set) return 'backup'
  return 'modules'
}

function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    return ''
  }
}

export default function WelcomePage() {
  const welcome = useQuery({ queryKey: ['welcome'], queryFn: getWelcome, retry: false })
  // Null until the owner moves: until then the step is wherever their saved
  // answers leave off.
  const [chosenStep, setStep] = useState<Step | null>(null)
  const [draft, setDraft] = useState<HotelDraft | null>(null)
  // "Add a hotel" on the Overview reopens just the hotel steps
  // (/welcome?add=hotel), however long ago the install was set up.
  const [addMode] = useState(
    () => new URLSearchParams(window.location.search).get('add') === 'hotel',
  )
  const finishedBefore = !addMode && welcome.data?.finished === true && chosenStep === null
  const step =
    chosenStep ??
    (welcome.data != null && !finishedBefore ? (addMode ? 'hotel' : firstStep(welcome.data)) : null)

  useEffect(() => {
    if (finishedBefore) window.location.replace('/overview')
  }, [finishedBefore])

  if (welcome.isError) {
    return (
      <Shell title="Something went wrong">
        <p role="alert" className="text-sm text-danger-red">
          {errorMessage(welcome.error)}
        </p>
      </Shell>
    )
  }
  if (welcome.data === null) {
    return (
      <Shell title="Nothing to set up here">
        <p className="text-sm text-ink-muted">This page belongs to the desktop edition.</p>
      </Shell>
    )
  }
  if (welcome.data === undefined || step === null) {
    return (
      <Shell>
        <p className="text-sm text-ink-muted">Loading …</p>
      </Shell>
    )
  }

  const state = welcome.data
  switch (step) {
    case 'group':
      return (
        <GroupStep
          initial={state.group_named ? state.group_name : ''}
          onDone={() =>
            setStep(
              state.properties.length === 0
                ? 'hotel'
                : state.backup_folder_set
                  ? 'modules'
                  : 'backup',
            )
          }
        />
      )
    case 'hotel':
      return (
        <HotelStep
          state={state}
          draft={draft}
          addMode={addMode}
          onNext={(d) => {
            setDraft(d)
            setStep('fiscal')
          }}
          onSkip={() => setStep(state.backup_folder_set ? 'modules' : 'backup')}
        />
      )
    case 'fiscal':
      return (
        <FiscalStep
          draft={draft as HotelDraft}
          addMode={addMode}
          onBack={() => setStep('hotel')}
          onDone={() => (addMode ? window.location.assign('/overview') : setStep('backup'))}
        />
      )
    case 'backup':
      return <BackupStep onDone={() => setStep('modules')} />
    case 'modules':
      return <ModulesStep onDone={() => setStep('done')} />
    case 'done':
      return <DoneStep />
  }
}

// --- pieces -----------------------------------------------------------------

function Shell({ step, title, children }: { step?: Step; title?: string; children: ReactNode }) {
  const number = step !== undefined && step !== 'done' ? STEP_NUMBER[step] : null
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-10">
      <p className="mb-6 text-lg font-semibold tracking-tight">
        <span aria-hidden="true" className="text-accent">
          ◆
        </span>{' '}
        <span className="text-accent">Open</span> Hospitality
      </p>
      <Card>
        {number !== null && <p className={sectionHeadClass}>Step {number} of 5</p>}
        {title !== undefined && <h1 className="mb-3 mt-1 text-xl font-semibold text-ink">{title}</h1>}
        {children}
      </Card>
    </main>
  )
}

function Label({ text, hint, children }: { text: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-ink-muted">{text}</span>
      {children}
      {hint !== undefined && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  )
}

function Refusal({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null
  return (
    <p role="alert" className="text-sm text-danger-red">
      {errorMessage(error)}
    </p>
  )
}

function GroupStep({ initial, onDone }: { initial: string; onDone: () => void }) {
  const [name, setName] = useState(initial)
  const save = useMutation({ mutationFn: () => nameGroup(name.trim()), onSuccess: onDone })

  return (
    <Shell step="group" title="Welcome — let’s set up your books">
      <p className="mb-5 text-sm text-ink-muted">
        Five short questions. You can change every answer later.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Label
          text="Your hotel group’s name"
          hint="The company or family name your hotels trade under — it’s fine if you have just one hotel."
        >
          <input
            aria-label="Your hotel group’s name"
            className={controlLargeClass}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Label>
        <Refusal error={save.error} />
        <div>
          <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Continue'}
          </button>
        </div>
      </form>
    </Shell>
  )
}

function HotelStep({
  state,
  draft,
  addMode,
  onNext,
  onSkip,
}: {
  state: WelcomeState
  draft: HotelDraft | null
  addMode: boolean
  onNext: (d: HotelDraft) => void
  onSkip: () => void
}) {
  const existing = state.properties
  const [adding, setAdding] = useState(addMode || existing.length === 0)
  const [entity, setEntity] = useState(draft?.ownership_entity ?? '')
  const [name, setName] = useState(draft?.name ?? '')
  const [code, setCode] = useState(draft?.code ?? '')
  const [reportName, setReportName] = useState(draft?.report_name ?? '')
  const [pms, setPms] = useState(draft?.pms_source ?? state.pms_choices[0]?.id ?? '')

  if (!adding) {
    return (
      <Shell step="hotel" title="Your hotels">
        <p className="mb-3 text-sm text-ink-muted">This copy of Open Hospitality already has:</p>
        <ul className="mb-5 list-disc pl-5 text-sm text-ink">
          {existing.map((p) => (
            <li key={p.property_id}>
              {p.name} <span className="text-ink-muted">({p.property_id})</span>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-3">
          <button type="button" className={primaryButtonClass} onClick={onSkip}>
            Continue
          </button>
          <button type="button" className={secondaryButtonClass} onClick={() => setAdding(true)}>
            Add another hotel
          </button>
        </div>
      </Shell>
    )
  }

  // Systems that print the hotel's code on every report are recognised by
  // it; the others print a name, so only they are asked how it's printed.
  const printsCode = state.pms_choices.find((c) => c.id === pms)?.prints_code ?? true
  const cleanCode = code.replace(/\s+/g, '').toUpperCase()
  const codeLooksRight = /^[A-Z0-9][A-Z0-9-]{1,19}$/.test(cleanCode)

  return (
    <Shell
      step={addMode ? undefined : 'hotel'}
      title={addMode ? 'Add a hotel' : 'Your first hotel'}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          onNext({
            ownership_entity: entity.trim(),
            name: name.trim(),
            code: cleanCode,
            report_name: printsCode ? '' : reportName.trim() || name.trim(),
            pms_source: pms,
          })
        }}
      >
        <Label
          text="Ownership entity name"
          hint="The company that owns this hotel, as it appears on its legal papers — for example “Carlsbad Hospitality LLC”."
        >
          <input
            aria-label="Ownership entity name"
            className={controlLargeClass}
            required
            maxLength={200}
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
          />
        </Label>
        <Label text="Hotel name">
          <input
            aria-label="Hotel name"
            className={controlLargeClass}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Label>
        <Label
          text="Hotel code"
          hint="The code your brand gives the hotel. It’s printed at the top of your night audit reports, next to “Property Code” — for example NM236."
        >
          <input
            aria-label="Hotel code"
            className={controlLargeClass}
            required
            maxLength={20}
            spellCheck={false}
            autoCapitalize="characters"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </Label>
        <Label text="Front-desk system (PMS)">
          <select
            aria-label="Front-desk system (PMS)"
            className={controlLargeClass}
            value={pms}
            onChange={(e) => setPms(e.target.value)}
          >
            {state.pms_choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Label>
        {!printsCode && (
          <Label
            text="The hotel’s name on your reports"
            hint="This system prints the hotel’s name rather than its code. Type it exactly as it’s printed at the top of a night audit report — capital letters don’t matter. Leave it blank if it’s the same as the hotel name."
          >
            <input
              aria-label="The hotel’s name on your reports"
              className={controlLargeClass}
              maxLength={200}
              placeholder={name.toUpperCase()}
              value={reportName}
              onChange={(e) => setReportName(e.target.value)}
            />
          </Label>
        )}
        <p className="text-xs text-ink-muted">
          No need to count rooms — Open Hospitality reads the room count from your first night
          audit.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            className={primaryButtonClass}
            disabled={!entity.trim() || !name.trim() || !codeLooksRight}
          >
            Continue
          </button>
          {addMode && (
            <a href="/overview" className={`${secondaryButtonClass} inline-flex items-center`}>
              Cancel
            </a>
          )}
        </div>
      </form>
    </Shell>
  )
}

function FiscalStep({
  draft,
  addMode,
  onBack,
  onDone,
}: {
  draft: HotelDraft
  addMode: boolean
  onBack: () => void
  onDone: () => void
}) {
  const [type, setType] = useState<FiscalChoice['calendar_type']>('calendar_month')
  const [startMonth, setStartMonth] = useState(1)
  const [weekday, setWeekday] = useState(0)
  const save = useMutation({
    mutationFn: () =>
      addHotel({
        ...draft,
        timezone: localTimezone(),
        fiscal: {
          calendar_type: type,
          fiscal_year_start_month: startMonth,
          week_start_weekday: type === '445' ? weekday : null,
        },
      }),
    onSuccess: onDone,
  })

  return (
    <Shell step={addMode ? undefined : 'fiscal'} title={`${draft.name}’s financial year`}>
      <p className="mb-5 text-sm text-ink-muted">
        Your statements are grouped into the periods of your financial year. Most hotels use
        calendar months starting in January — if you’re not sure, ask your accountant. You can
        change this later on the Property config page.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <fieldset className="flex flex-col gap-2 text-sm text-ink">
          <legend className="mb-1 text-xs font-medium text-ink-muted">Periods</legend>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="calendar"
              className="mt-0.5"
              checked={type === 'calendar_month'}
              onChange={() => setType('calendar_month')}
            />
            <span>
              Calendar months <span className="text-ink-muted">— most hotels</span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="calendar"
              className="mt-0.5"
              checked={type === '445'}
              onChange={() => setType('445')}
            />
            <span>
              4-4-5 weeks{' '}
              <span className="text-ink-muted">— each quarter is two 4-week periods and a 5-week one</span>
            </span>
          </label>
        </fieldset>
        <Label text="The financial year starts in">
          <select
            aria-label="The financial year starts in"
            className={controlLargeClass}
            value={startMonth}
            onChange={(e) => setStartMonth(Number(e.target.value))}
          >
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </Label>
        {type === '445' && (
          <Label text="Weeks start on">
            <select
              aria-label="Weeks start on"
              className={controlLargeClass}
              value={weekday}
              onChange={(e) => setWeekday(Number(e.target.value))}
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </Label>
        )}
        <Refusal error={save.error} />
        <div className="flex flex-wrap gap-3">
          <button type="button" className={secondaryButtonClass} onClick={onBack} disabled={save.isPending}>
            Back
          </button>
          <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save and continue'}
          </button>
        </div>
      </form>
    </Shell>
  )
}

/** PRD I-6 and the risks table's severe row: the folder is chosen HERE, while
 * the owner is setting up, not in a settings page they never open. The
 * recovery code was wrapped when their account was made, so this step only
 * needs somewhere to put the file. */
function BackupStep({ onDone }: { onDone: () => void }) {
  const status = useQuery({ queryKey: ['backup'], queryFn: getBackupStatus, retry: false })
  const [folder, setFolder] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (value: string) => setBackupFolder(value),
    onSuccess: onDone,
  })
  const typed = folder ?? status.data?.folder ?? status.data?.suggested_folder ?? ''

  return (
    <Shell step="backup" title="Keep a copy of your books">
      <p className="mb-5 text-sm text-ink-muted">
        If this computer is lost, stolen or replaced, a backup is what brings your books back.
        Choose a folder your cloud drive already syncs — OneDrive, iCloud, Dropbox — and Open
        Hospitality writes a copy there each day. Your recovery code opens it on a new computer.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate(typed.trim())
        }}
      >
        <Label text="Backup folder" hint="It's created for you if it isn't there yet.">
          <input
            aria-label="Backup folder"
            className={controlLargeClass}
            spellCheck={false}
            value={typed}
            onChange={(e) => setFolder(e.target.value)}
          />
        </Label>
        <Refusal error={save.error} />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            className={primaryButtonClass}
            disabled={save.isPending || typed.trim() === ''}
          >
            {save.isPending ? 'Saving…' : 'Save and continue'}
          </button>
          <button type="button" className={secondaryButtonClass} onClick={onDone}>
            Skip for now
          </button>
        </div>
      </form>
      <p className="mt-3 text-xs text-ink-muted">
        Skip it and your books live on this computer alone. The Overview will keep reminding you.
      </p>
    </Shell>
  )
}

function ModulesStep({ onDone }: { onDone: () => void }) {
  const modules = useQuery({ queryKey: ['modules'], queryFn: getModules, retry: false })
  const [chosen, setChosen] = useState<Set<string> | null>(null)
  const [switching, setSwitching] = useState(false)
  const list = modules.data?.modules ?? []
  const picked = chosen ?? new Set(list.filter((m) => m.enabled).map((m) => m.id))

  const finish = useMutation({
    mutationFn: async () => {
      await finishWelcome()
      const saved = await saveModules([...picked])
      if (saved.reloading) {
        setSwitching(true)
        await waitForModules(saved.modules.filter((m) => m.enabled).map((m) => m.id))
      }
    },
    onSuccess: onDone,
    onSettled: () => setSwitching(false),
  })

  function toggle(m: DesktopModule) {
    const next = new Set(picked)
    if (next.has(m.id)) next.delete(m.id)
    else next.add(m.id)
    setChosen(next)
  }

  return (
    <Shell step="modules" title="What would you like to use?">
      <p className="mb-5 text-sm text-ink-muted">
        Turn on only what you need. You can change this at any time on the Modules page — turning
        something off hides it and deletes nothing.
      </p>
      {modules.isPending && <p className="text-sm text-ink-muted">Loading …</p>}
      <Refusal error={modules.error} />
      <div className="flex flex-col gap-3">
        {list.map((m) => (
          <ModuleChoice key={m.id} module={m} on={picked.has(m.id)} onToggle={() => toggle(m)} />
        ))}
      </div>
      {switching && (
        <p role="status" className="mt-4 text-sm text-ink-muted">
          Switching… this takes a few seconds.
        </p>
      )}
      <div className="mt-4">
        <Refusal error={finish.error} />
      </div>
      <div className="mt-4">
        <button
          type="button"
          className={primaryButtonClass}
          disabled={finish.isPending || modules.data == null}
          onClick={() => finish.mutate()}
        >
          {finish.isPending ? 'Finishing…' : 'Finish'}
        </button>
      </div>
    </Shell>
  )
}

function ModuleChoice({
  module: m,
  on,
  onToggle,
}: {
  module: DesktopModule
  on: boolean
  onToggle: () => void
}) {
  const selectable = m.status === 'available' && !m.required
  return (
    <div role="group" aria-label={m.name} className="rounded-lg border border-line p-3">
      <label className={`flex items-start gap-2 ${selectable ? '' : 'cursor-default'}`}>
        <input
          type="checkbox"
          className="mt-1"
          checked={m.required || (m.status === 'available' && on)}
          disabled={!selectable}
          onChange={onToggle}
        />
        <span>
          <span className="block text-sm font-semibold text-ink">
            {m.name}
            {m.required && <span className="ml-2 text-xs font-normal text-ink-muted">Always on</span>}
            {m.status === 'coming_soon' && (
              <span className="ml-2 text-xs font-normal text-ink-muted">Coming soon</span>
            )}
          </span>
          <span className="block text-sm text-ink-muted">{m.summary}</span>
        </span>
      </label>
      <details className="mt-2 pl-6 text-sm">
        <summary className="cursor-pointer text-ink-muted">What this can’t do</summary>
        <ul className="mt-1 list-disc pl-5 text-ink">
          {m.limitations.map((lim) => (
            <li key={lim.text} className="py-0.5">
              {lim.text}
              {lim.workaround !== null && (
                <span className="block text-ink-muted">What you can do: {lim.workaround}</span>
              )}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function DoneStep() {
  return (
    <Shell title="You’re set up">
      <p className="text-sm text-ink">
        Now give Open Hospitality your night audit reports. Put them in the{' '}
        <strong>Drop reports here</strong> folder inside <strong>Documents › Open Hospitality</strong>
        , or use <strong>Upload</strong> in the app. Each report is read within a few seconds.
      </p>
      <p className="mt-3 text-sm text-ink-muted">
        The Setup page shows anything still left to do.
      </p>
      <button
        type="button"
        className={`${primaryButtonClass} mt-5`}
        onClick={() => window.location.assign('/setup')}
      >
        Open my books
      </button>
    </Shell>
  )
}
