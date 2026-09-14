import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getFolders: vi.fn(),
  openFolder: vi.fn(),
}))

import { getFolders, openFolder, type OwnerFolders } from '../api/desktop'
import FoldersCard from './FoldersCard'

const FOLDERS: OwnerFolders = {
  root: 'C:/Users/pat/Documents/Open Hospitality',
  folders: [
    { id: 'saved', name: 'Saved reports', files: 2,
      path: 'C:/Users/pat/Documents/Open Hospitality/Saved reports',
      what: 'Daily summaries (PDF) and each month’s accountant pack (Excel).' },
    { id: 'read', name: 'Reports we read', files: 1,
      path: 'C:/Users/pat/Documents/Open Hospitality/Reports we read',
      what: 'Every night audit PDF that has been read.' },
  ],
}

function renderCard(only?: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <FoldersCard only={only} />
    </QueryClientProvider>,
  )
}

describe('FoldersCard', () => {
  beforeEach(() => {
    vi.mocked(getFolders).mockReset().mockResolvedValue(FOLDERS)
    vi.mocked(openFolder).mockReset().mockResolvedValue(undefined)
  })

  it('says which folder holds everything, and what each one is for', async () => {
    renderCard()
    const card = await screen.findByRole('region', { name: 'Your report folders' })
    expect(within(card).getByText(FOLDERS.root)).toBeInTheDocument()
    expect(within(card).getByText('Saved reports')).toBeInTheDocument()
    expect(within(card).getByText(/· 2 files/)).toBeInTheDocument()
    expect(within(card).getByText(/· 1 file$/)).toBeInTheDocument()
    expect(within(card).getByText(/accountant pack/)).toBeInTheDocument()
  })

  it('opens a folder by its name, never by a path', async () => {
    renderCard()
    const buttons = await screen.findAllByRole('button', { name: 'Open folder' })
    await userEvent.click(buttons[0] as HTMLElement)
    await waitFor(() => expect(openFolder).toHaveBeenCalledWith('saved'))
  })

  it('can show just some of them', async () => {
    renderCard(['read'])
    await screen.findByRole('region', { name: 'Your report folders' })
    expect(screen.queryByText('Saved reports')).toBeNull()
  })

  it('is nothing outside the desktop edition', async () => {
    vi.mocked(getFolders).mockResolvedValue(null)
    renderCard()
    await waitFor(() => expect(getFolders).toHaveBeenCalled())
    expect(screen.queryByRole('region', { name: 'Your report folders' })).toBeNull()
  })
})
