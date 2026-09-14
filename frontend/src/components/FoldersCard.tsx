// Desktop edition: where the owner's reports are, and a button to open each
// (src/usali/desktop/folders_api.py). Asked for by the owner: "show which
// folder has all reports". Renders nothing outside the desktop edition.
import { useMutation, useQuery } from '@tanstack/react-query'

import { getFolders, openFolder } from '../api/desktop'
import { errorMessage } from '../lib/errors'
import { Card, sectionHeadClass } from './ui'

const buttonClass =
  'shrink-0 rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'

export default function FoldersCard({ only }: { only?: string[] }) {
  const folders = useQuery({ queryKey: ['folders'], queryFn: getFolders, retry: false })
  const open = useMutation({ mutationFn: (id: string) => openFolder(id) })

  if (folders.data == null) return null
  const shown = folders.data.folders.filter((f) => only === undefined || only.includes(f.id))

  return (
    <Card role="region" aria-label="Your report folders">
      <h2 className={sectionHeadClass}>Your report folders</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Everything is in <span className="font-medium text-ink">{folders.data.root}</span>
      </p>
      <ul className="mt-3 divide-y divide-line">
        {shown.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">
                {f.name}{' '}
                <span className="font-normal text-ink-muted">
                  · {f.files} file{f.files === 1 ? '' : 's'}
                </span>
              </p>
              <p className="text-xs text-ink-muted">{f.what}</p>
              <p className="break-all text-xs text-ink-muted">{f.path}</p>
            </div>
            <button
              type="button"
              className={buttonClass}
              disabled={open.isPending}
              onClick={() => open.mutate(f.id)}
            >
              Open folder
            </button>
          </li>
        ))}
      </ul>
      {open.isError && (
        <p role="alert" className="mt-2 text-sm text-danger-red">
          {errorMessage(open.error)}
        </p>
      )}
    </Card>
  )
}
