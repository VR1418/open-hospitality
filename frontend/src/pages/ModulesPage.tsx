// Desktop edition: the module chooser's permanent home beside Setup
// (PRD 5.2, L-1). Each module states what it can't do on the same screen as
// the switch (L-3), from the server's ModuleRegistry — never a copy here.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { getMe } from '../api/client'
import { getModules, saveModules, type DesktopModule } from '../api/desktop'
import { Badge, Card, PageHeader, sectionHeadClass, type BadgeTone } from '../components/ui'
import { errorMessage } from '../lib/errors'
import { hasRole } from '../lib/roles'

const buttonClass =
  'shrink-0 rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x))
}

/** After a change the local server rebuilds itself; ask until it answers
 * with the new set mounted (a few seconds at most). */
async function waitForModules(enabled: string[]): Promise<void> {
  for (let i = 0; i < 40; i++) {
    await new Promise((resolve) => setTimeout(resolve, 500))
    try {
      const now = await getModules()
      const on = (now?.modules ?? []).filter((m) => m.enabled).map((m) => m.id)
      if (sameSet(on, enabled)) return
    } catch {
      // The server is between builds; keep asking.
    }
  }
  throw new Error('Open Hospitality is taking longer than usual to switch. Reload this page.')
}

function statusOf(m: DesktopModule): { tone: BadgeTone; word: string } {
  if (m.status === 'coming_soon') return { tone: 'neutral', word: 'Coming soon' }
  return m.enabled ? { tone: 'ok', word: 'On' } : { tone: 'neutral', word: 'Off' }
}

export default function ModulesPage() {
  const queryClient = useQueryClient()
  const modules = useQuery({ queryKey: ['modules'], queryFn: getModules, retry: false })
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  // Mirrors the endpoint's gate: choosing modules is the owner's call.
  const canChange = hasRole(me.data, 'org_admin')
  const [switching, setSwitching] = useState(false)

  const list = modules.data?.modules ?? []
  const enabledIds = list.filter((m) => m.enabled).map((m) => m.id)

  const change = useMutation({
    mutationFn: async (enabled: string[]) => {
      const saved = await saveModules(enabled)
      if (saved.reloading) {
        setSwitching(true)
        await waitForModules(saved.modules.filter((m) => m.enabled).map((m) => m.id))
      }
    },
    onSettled: async () => {
      setSwitching(false)
      await queryClient.invalidateQueries({ queryKey: ['modules'] })
    },
  })

  function toggle(m: DesktopModule) {
    change.mutate(
      m.enabled ? enabledIds.filter((id) => id !== m.id) : [...enabledIds, m.id],
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Modules"
        subtitle="Choose what Open Hospitality does for you. You can change this at any time — turning a module off hides it, and deletes nothing."
      />
      {switching && (
        <p role="status" className="text-sm text-ink-muted">
          Switching… this takes a few seconds.
        </p>
      )}
      {modules.isError && (
        <Card>
          <p className="text-sm text-danger-red">
            Couldn’t load your modules: {errorMessage(modules.error)}
          </p>
        </Card>
      )}
      {change.isError && (
        <Card>
          <p role="alert" className="text-sm text-danger-red">
            {errorMessage(change.error)}
          </p>
        </Card>
      )}
      {modules.isPending && (
        <Card>
          <p className="text-sm text-ink-muted">Loading …</p>
        </Card>
      )}
      {list.map((m) => (
        <ModuleCard
          key={m.id}
          module={m}
          canChange={canChange}
          busy={change.isPending}
          onToggle={() => toggle(m)}
        />
      ))}
    </div>
  )
}

function ModuleCard({
  module: m,
  canChange,
  busy,
  onToggle,
}: {
  module: DesktopModule
  canChange: boolean
  busy: boolean
  onToggle: () => void
}) {
  const status = statusOf(m)
  const verb = m.enabled ? 'Turn off' : 'Turn on'
  return (
    <Card role="region" aria-label={m.name}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold text-ink">
            {m.name}
            <Badge tone={status.tone}>{status.word}</Badge>
          </h2>
          <p className="mt-1 text-sm text-ink-muted">{m.summary}</p>
        </div>
        {m.required ? (
          <span className="shrink-0 text-xs text-ink-muted">Always on</span>
        ) : m.status === 'available' && canChange ? (
          <button
            type="button"
            className={buttonClass}
            disabled={busy}
            aria-label={`${verb} ${m.name}`}
            onClick={onToggle}
          >
            {verb}
          </button>
        ) : null}
      </div>
      <h3 className={`${sectionHeadClass} mt-4`}>What this can’t do</h3>
      <ul className="mt-1 list-disc pl-5 text-sm text-ink">
        {m.limitations.map((lim) => (
          <li key={lim.text} className="py-1">
            {lim.text}
            {lim.workaround !== null && (
              <span className="block text-ink-muted">What you can do: {lim.workaround}</span>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}
