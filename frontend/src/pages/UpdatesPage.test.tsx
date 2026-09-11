import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UpdateStatus } from '../api/desktop'
import UpdatesPage from './UpdatesPage'

const getUpdate = vi.fn<() => Promise<UpdateStatus | null>>()
const checkForUpdate = vi.fn<() => Promise<UpdateStatus>>()

vi.mock('../api/desktop', () => ({
  getUpdate: () => getUpdate(),
  checkForUpdate: () => checkForUpdate(),
}))

const NOT_SET_UP: UpdateStatus = {
  configured: false, current: '0.1.0', latest: null, url: null, notes: null,
  checked_at: null, error: null, update_available: false,
}
const UP_TO_DATE: UpdateStatus = {
  ...NOT_SET_UP, configured: true, latest: '0.1.0', checked_at: '2026-09-11T06:00:00Z',
}
const NEWER: UpdateStatus = {
  ...UP_TO_DATE, latest: '0.2.0', url: 'https://example.test/download',
  notes: 'Backups, and a menu in plain words.', update_available: true,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UpdatesPage />
    </QueryClientProvider>,
  )
}

describe('UpdatesPage', () => {
  beforeEach(() => {
    getUpdate.mockReset().mockResolvedValue(NOT_SET_UP)
    checkForUpdate.mockReset().mockResolvedValue(NEWER)
  })

  it('says which version this copy is', async () => {
    renderPage()
    const copy = await screen.findByRole('region', { name: 'This copy' })
    expect(within(copy).getByText('Version 0.1.0')).toBeInTheDocument()
  })

  it('is honest that checks are not set up yet, and cannot be run', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'Newer version' })
    expect(within(region).getByText(/aren’t set up yet/)).toBeInTheDocument()
    expect(within(region).getByRole('button', { name: 'Check now' })).toBeDisabled()
  })

  it('says so plainly when there is nothing newer', async () => {
    getUpdate.mockResolvedValue(UP_TO_DATE)
    renderPage()
    const region = await screen.findByRole('region', { name: 'Newer version' })
    expect(within(region).getByText('You’re on the latest version.')).toBeInTheDocument()
  })

  it('names the newer version, what changed, and where to get it', async () => {
    getUpdate.mockResolvedValue(NEWER)
    renderPage()
    const region = await screen.findByRole('region', { name: 'Newer version' })
    expect(within(region).getByText('Version 0.2.0')).toBeInTheDocument()
    expect(within(region).getByText('Backups, and a menu in plain words.')).toBeInTheDocument()
    expect(within(region).getByRole('link', { name: 'Download version 0.2.0' })).toHaveAttribute(
      'href',
      'https://example.test/download',
    )
    // It offers a download, never an install that happened without asking.
    expect(within(region).getByText(/Install it when it suits you/)).toBeInTheDocument()
  })

  it('checks again when asked', async () => {
    getUpdate.mockResolvedValue(UP_TO_DATE)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Check now' }))
    expect(checkForUpdate).toHaveBeenCalled()
    expect(await screen.findByText('Version 0.2.0')).toBeInTheDocument()
  })

  it('a check that could not reach the file is a line, not a broken page', async () => {
    getUpdate.mockResolvedValue({ ...UP_TO_DATE, error: 'connection refused' })
    renderPage()
    expect(await screen.findByRole('status')).toHaveTextContent('connection refused')
    expect(screen.getByText('You’re on the latest version.')).toBeInTheDocument()
  })

  it('says what it sends: nothing', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'What is sent' })
    expect(within(region).getByText(/Nothing about you or your hotels/)).toBeInTheDocument()
  })

  it('on a hosted deployment, says updates are a desktop feature', async () => {
    getUpdate.mockResolvedValue(null)
    renderPage()
    expect(await screen.findByText(/part of the desktop edition/)).toBeInTheDocument()
  })
})
