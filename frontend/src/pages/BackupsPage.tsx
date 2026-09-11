// Desktop edition: backups (PRD I-6, ADR-D4). A copy of the books in a folder
// the owner's cloud drive already syncs, openable on another computer with the
// recovery code they already keep.
//
// The copy is taken while the database is STOPPED, which is only true before
// Open Hospitality starts — so "Back up now" honestly says "next time you
// start it" rather than pretending to run one.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  armBackups,
  backupNow,
  getBackupStatus,
  setBackupFolder,
  type BackupFile,
} from '../api/desktop'
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

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

function when(iso: string | null): string {
  if (iso === null) return 'never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function FileRow({ file }: { file: BackupFile }) {
  return (
    <tr className="border-t border-line">
      <td className={cellClass}>{file.name}</td>
      <td className={cellClass}>{when(file.taken_at)}</td>
      <td className={`${cellClass} text-right tabular-nums`}>{file.size_mb} MB</td>
      <td className={cellClass}>
        {file.readable ? (
          <Badge tone="ok">Ready</Badge>
        ) : (
          <Badge tone="danger">Can’t be read</Badge>
        )}
      </td>
    </tr>
  )
}

export default function BackupsPage() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['backup'], queryFn: getBackupStatus, retry: false })
  const [folder, setFolder] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['backup'] })

  const save = useMutation({
    mutationFn: (value: string) => setBackupFolder(value),
    onSuccess: () => {
      setFolder(null)
      void refresh()
    },
  })
  const arm = useMutation({
    mutationFn: () => armBackups(code),
    onSuccess: () => {
      setCode('')
      void refresh()
    },
  })
  const now = useMutation({ mutationFn: backupNow, onSuccess: refresh })

  if (status.isPending) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">Loading …</p>
      </Card>
    )
  }
  if (status.isError) {
    return (
      <Card>
        <p role="alert" className="text-sm text-danger-red">
          Couldn’t read your backup settings: {errorMessage(status.error)}
        </p>
      </Card>
    )
  }
  const data = status.data
  if (data === null) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">Backups are part of the desktop edition.</p>
      </Card>
    )
  }
  const typed = folder ?? data.folder ?? data.suggested_folder

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Backups"
        subtitle="A copy of your books, in a folder your cloud drive already syncs."
      />

      <Card role="region" aria-label="Where backups go">
        <h2 className={sectionHeadClass}>Where backups go</h2>
        <form
          className="mt-2 flex flex-col gap-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            save.mutate(typed)
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-ink-muted">
              Folder (in OneDrive, iCloud, Dropbox — anywhere that syncs)
            </span>
            <input
              aria-label="Backup folder"
              className={controlLargeClass}
              value={typed}
              spellCheck={false}
              onChange={(e) => setFolder(e.target.value)}
            />
          </label>
          {save.isError && (
            <p role="alert" className="text-sm text-danger-red">
              {errorMessage(save.error)}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save folder'}
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={data.folder === null || now.isPending}
              onClick={() => now.mutate()}
            >
              Back up now
            </button>
            <span className="text-sm text-ink-muted">
              Last backup: {when(data.last_backup_at)}
              {data.due && data.folder !== null && ' · one is due at the next start'}
            </span>
          </div>
          {now.isSuccess && (
            <p role="status" className="text-sm text-ink-muted">
              {now.data.detail}
            </p>
          )}
          {now.isError && (
            <p role="alert" className="text-sm text-danger-red">
              {errorMessage(now.error)}
            </p>
          )}
        </form>
      </Card>

      <Card role="region" aria-label="Opening a backup on another computer">
        <h2 className={sectionHeadClass}>Opening a backup on another computer</h2>
        {data.armed ? (
          <p className="mt-2 text-sm text-ink">
            <Badge tone="ok">Ready</Badge>{' '}
            Your backups can be opened with your recovery code — the one you saved when you set
            up Open Hospitality. Keep it somewhere that isn’t this computer.
          </p>
        ) : (
          <>
            <p className="mt-2 text-sm text-ink">
              Type your recovery code once. Until you do, a backup can only be opened on this
              computer — which is no help if this is the computer you’ve lost.
            </p>
            <form
              className="mt-3 flex flex-wrap items-end gap-3"
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                arm.mutate()
              }}
            >
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-ink-muted">
                  Recovery code
                </span>
                <input
                  aria-label="Recovery code"
                  className={controlLargeClass}
                  autoComplete="off"
                  spellCheck={false}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </label>
              <button type="submit" className={primaryButtonClass} disabled={arm.isPending}>
                {arm.isPending ? 'Checking…' : 'Confirm'}
              </button>
            </form>
            {arm.isError && (
              <p role="alert" className="mt-2 text-sm text-danger-red">
                {errorMessage(arm.error)}
              </p>
            )}
          </>
        )}
      </Card>

      <Card role="region" aria-label="Backups in that folder">
        <h2 className={sectionHeadClass}>Backups in that folder</h2>
        <p className="mt-1 text-xs text-ink-muted">
          The last {data.keep} are kept; older ones are removed as new ones arrive.
        </p>
        {data.files.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">
            No backups yet.{data.folder === null && ' Choose a folder above.'}
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={headCellClass}>File</th>
                  <th className={headCellClass}>Taken</th>
                  <th className={`${headCellClass} text-right`}>Size</th>
                  <th className={headCellClass}>
                    <span className="sr-only">State</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <FileRow key={f.name} file={f} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card role="region" aria-label="Putting a backup back">
        <h2 className={sectionHeadClass}>Putting a backup back</h2>
        <p className="mt-2 text-sm text-ink">
          On a computer with no books yet, start Open Hospitality with the backup file and your
          recovery code. It won’t write over books that are already there.
        </p>
        <p className="mt-2 font-mono text-xs text-ink-muted">
          oh-desktop --restore &quot;&lt;your backup file&gt;&quot;
        </p>
        <p className="mt-2 text-sm text-ink-muted">
          A backup holds your books and their keys — not the report PDFs, which are already in
          your Open Hospitality folder.
        </p>
      </Card>
    </div>
  )
}
