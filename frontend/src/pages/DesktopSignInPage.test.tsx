import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DesktopSignInPage from './DesktopSignInPage'

const storeDesktopSession = vi.fn<(token: string, expiresIn: number) => Promise<void>>()

vi.mock('../auth/oidc', () => ({
  storeDesktopSession: (token: string, expiresIn: number) => storeDesktopSession(token, expiresIn),
}))

function arriveAt(url: string) {
  window.history.replaceState(null, '', url)
}

describe('DesktopSignInPage', () => {
  beforeEach(() => {
    storeDesktopSession.mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    storeDesktopSession.mockReset()
    arriveAt('/')
  })

  it('trades the one-time code for a session and scrubs it from the address bar', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'tok', token_type: 'Bearer', expires_in: 60 }), {
        status: 200,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    arriveAt('/desktop-signin#code=abc123')

    render(<DesktopSignInPage />)

    await waitFor(() => expect(storeDesktopSession).toHaveBeenCalledWith('tok', 60))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/desktop/session')
    expect(JSON.parse(String(init.body))).toEqual({ code: 'abc123' })
    // A spent one-time code has no business in history.
    expect(window.location.hash).toBe('')
  })

  it('shows the server’s refusal, which names the next step', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Link expired. Open it again from the icon.' }), {
          status: 401,
        }),
      ),
    )
    arriveAt('/desktop-signin#code=spent')

    render(<DesktopSignInPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Link expired. Open it again from the icon.',
    )
    expect(storeDesktopSession).not.toHaveBeenCalled()
  })

  it('without a code, explains how to open the books — and asks the server nothing', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    arriveAt('/desktop-signin?signed-out=1')

    render(<DesktopSignInPage />)

    expect(await screen.findByText(/You’re signed out/)).toHaveTextContent('Open my books')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
