import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BackupStatus } from '../api/desktop'
import BackupsPage from './BackupsPage'

const getBackupStatus = vi.fn<() => Promise<BackupStatus | null>>()
const setBackupFolder = vi.fn<(folder: string) => Promise<BackupStatus>>()
const armBackups = vi.fn<(code: string) => Promise<void>>()
const backupNow = vi.fn<() => Promise<{ detail: string }>>()
const pickFolder = vi.fn<(start: string, title: string) => Promise<string | null>>()

vi.mock('../api/desktop', () => ({
  getBackupStatus: () => getBackupStatus(),
  setBackupFolder: (folder: string) => setBackupFolder(folder),
  armBackups: (code: string) => armBackups(code),
  backupNow: () => backupNow(),
  pickFolder: (start: string, title: string) => pickFolder(start, title),
}))

const READY: BackupStatus = {
  folder: 'C:\\Users\\pat\\OneDrive\\Hotel backups',
  suggested_folder: 'C:\\Users\\pat\\Documents\\Open Hospitality\\Backups',
  last_backup_at: '2026-09-11T04:10:00Z',
  last_file: 'Open Hospitality 2026-09-11 0410.ohbackup',
  armed: true,
  due: false,
  keep: 7,
  files: [
    {
      name: 'Open Hospitality 2026-09-11 0410.ohbackup', size_mb: 41.2,
      taken_at: '2026-09-11T04:10:00Z', app_version: '0.1.0', readable: true,
    },
    {
      name: 'Open Hospitality 2026-09-10 0405.ohbackup', size_mb: 40.9,
      taken_at: null, app_version: null, readable: false,
    },
  ],
}

const FRESH: BackupStatus = {
  ...READY,
  folder: null,
  last_backup_at: null,
  last_file: null,
  armed: false,
  due: false,
  files: [],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BackupsPage />
    </QueryClientProvider>,
  )
}

describe('BackupsPage', () => {
  beforeEach(() => {
    getBackupStatus.mockReset().mockResolvedValue(READY)
    setBackupFolder.mockReset().mockResolvedValue(READY)
    armBackups.mockReset().mockResolvedValue(undefined)
    backupNow.mockReset().mockResolvedValue({
      detail: 'Open Hospitality will back up the next time you start it.',
    })
  })

  it('shows where backups go, when the last one was taken, and what is there', async () => {
    renderPage()
    expect(await screen.findByLabelText('Backup folder')).toHaveValue(READY.folder)
    const files = screen.getByRole('region', { name: 'Backups in that folder' })
    expect(within(files).getByText('41.2 MB')).toBeInTheDocument()
    expect(within(files).getByText('The last 7 are kept; older ones are removed as new ones arrive.'))
      .toBeInTheDocument()
    // A file the app can't read is said to be unreadable, not listed as fine.
    expect(within(files).getByText('Can’t be read')).toBeInTheDocument()
  })

  it('offers the suggested folder when none is chosen, and saves the one typed', async () => {
    getBackupStatus.mockResolvedValue(FRESH)
    renderPage()
    const input = await screen.findByLabelText('Backup folder')
    expect(input).toHaveValue(FRESH.suggested_folder)

    await userEvent.clear(input)
    await userEvent.type(input, 'D:\\Dropbox\\Hotel')
    await userEvent.click(screen.getByRole('button', { name: 'Save folder' }))
    expect(setBackupFolder).toHaveBeenCalledWith('D:\\Dropbox\\Hotel')
  })

  it('says when the copy will actually happen', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Back up now' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      'back up the next time you start it',
    )
  })

  it('cannot ask for a backup before a folder is chosen', async () => {
    getBackupStatus.mockResolvedValue(FRESH)
    renderPage()
    expect(await screen.findByRole('button', { name: 'Back up now' })).toBeDisabled()
  })

  it('asks for the recovery code once, and says why it matters', async () => {
    getBackupStatus.mockResolvedValue(FRESH)
    renderPage()
    const region = await screen.findByRole('region', {
      name: 'Opening a backup on another computer',
    })
    expect(within(region).getByText(/no help if this is the computer you’ve lost/))
      .toBeInTheDocument()
    await userEvent.type(within(region).getByLabelText('Recovery code'), 'Z177D-WHZ9P')
    await userEvent.click(within(region).getByRole('button', { name: 'Confirm' }))
    expect(armBackups).toHaveBeenCalledWith('Z177D-WHZ9P')
  })

  it('shows the server’s refusal when the code is wrong', async () => {
    getBackupStatus.mockResolvedValue(FRESH)
    armBackups.mockRejectedValue(new Error('That recovery code doesn’t match this account.'))
    renderPage()
    await userEvent.type(await screen.findByLabelText('Recovery code'), 'WRONG')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('doesn’t match')
  })

  it('once armed, it stops asking and says the backups are ready', async () => {
    renderPage()
    const region = await screen.findByRole('region', {
      name: 'Opening a backup on another computer',
    })
    expect(within(region).getByText('Ready')).toBeInTheDocument()
    expect(within(region).queryByLabelText('Recovery code')).toBeNull()
  })

  it('tells the owner how to put a backup back, without a command line', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'Putting a backup back' })
    expect(within(region).getByText(/Double-click the backup file/)).toBeInTheDocument()
    expect(within(region).queryByText(/--restore/)).toBeNull()
    expect(within(region).getByText(/won’t write over books that are already on a computer/))
      .toBeInTheDocument()
  })

  it('chooses the folder in a dialog and saves what was chosen', async () => {
    getBackupStatus.mockResolvedValue(FRESH)
    setBackupFolder.mockResolvedValue(READY)
    pickFolder.mockResolvedValueOnce(null).mockResolvedValueOnce('D:\\Hotel backups')
    renderPage()
    const choose = await screen.findByRole('button', { name: 'Choose folder…' })
    await userEvent.click(choose)
    await waitFor(() => expect(pickFolder).toHaveBeenCalledTimes(1))
    expect(setBackupFolder).not.toHaveBeenCalled() // cancelled
    await userEvent.click(choose)
    await waitFor(() => expect(setBackupFolder).toHaveBeenCalledWith('D:\\Hotel backups'))
  })

  it('on a hosted deployment, says backups are a desktop feature', async () => {
    getBackupStatus.mockResolvedValue(null)
    renderPage()
    expect(await screen.findByText(/part of the desktop edition/)).toBeInTheDocument()
  })

  it('a refused read is shown, not swallowed', async () => {
    getBackupStatus.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  })

  it('waits for the folder to be saved before asking again', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Save folder' }))
    await waitFor(() => expect(setBackupFolder).toHaveBeenCalledWith(READY.folder))
  })
})
