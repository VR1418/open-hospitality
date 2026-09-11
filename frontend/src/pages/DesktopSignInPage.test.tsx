import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DesktopSignInPage from './DesktopSignInPage'

const storeDesktopSession = vi.fn<(token: string, expiresIn: number) => Promise<void>>()
const getUser = vi.fn<() => Promise<{ expired: boolean } | null>>()
const clearDesktopSession = vi.fn<() => Promise<void>>()

vi.mock('../auth/oidc', () => ({
  storeDesktopSession: (token: string, expiresIn: number) => storeDesktopSession(token, expiresIn),
  getUser: () => getUser(),
  clearDesktopSession: () => clearDesktopSession(),
}))

function arriveAt(url: string) {
  window.history.replaceState(null, '', url)
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
}

const TOKEN = { access_token: 'tok', token_type: 'Bearer', expires_in: 60 }

/** The local server, by path: a fresh Response per call (a body reads once). */
function server(routes: Record<string, () => Response>) {
  const fetchMock = vi.fn((url: string) => {
    const route = routes[url]
    return Promise.resolve(route === undefined ? json(404, { detail: 'Not Found' }) : route())
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bodyOf(fetchMock: ReturnType<typeof server>, url: string): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(([u]) => u === url) as unknown as [string, RequestInit]
  return JSON.parse(String(call[1].body)) as Record<string, unknown>
}

async function fill(label: string, value: string) {
  await userEvent.type(screen.getByLabelText(label), value)
}

describe('DesktopSignInPage', () => {
  beforeEach(() => {
    storeDesktopSession.mockResolvedValue(undefined)
    getUser.mockResolvedValue(null)
    clearDesktopSession.mockResolvedValue(undefined)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    storeDesktopSession.mockReset()
    getUser.mockReset()
    clearDesktopSession.mockReset()
    arriveAt('/')
  })

  describe('first run', () => {
    it('creates the owner with the launch code, then shows the recovery code once', async () => {
      const fetchMock = server({
        '/api/desktop/status': () => json(200, { setup_required: true }),
        '/api/desktop/setup/owner': () =>
          json(201, { ...TOKEN, recovery_code: 'ABCDE-FGHJK-MNPQR-STVWX-YZ012' }),
      })
      arriveAt('/desktop-signin#code=launch-123')

      render(<DesktopSignInPage />)

      await screen.findByRole('heading', { name: 'Set up your books' })
      // A one-time code has no business in history.
      expect(window.location.hash).toBe('')
      await fill('Your full name', 'Pat Owner')
      await fill('Email', 'pat@hotel.test')
      await fill('Password', 'correct horse battery')
      await fill('Type the password again', 'correct horse battery')
      await userEvent.click(screen.getByRole('button', { name: 'Set up my books' }))

      expect(await screen.findByLabelText('Recovery code')).toHaveTextContent(
        'ABCDE-FGHJK-MNPQR-STVWX-YZ012',
      )
      expect(bodyOf(fetchMock, '/api/desktop/setup/owner')).toMatchObject({
        code: 'launch-123',
        full_name: 'Pat Owner',
        email: 'pat@hotel.test',
        password: 'correct horse battery',
      })
      expect(storeDesktopSession).toHaveBeenCalledWith('tok', 60)
      // A-6: the warning, and no way past it without saying it's saved.
      expect(screen.getByText(/nobody — not even us — can open your books/)).toBeInTheDocument()
      const go = screen.getByRole('button', { name: 'Open my books' })
      expect(go).toBeDisabled()
      await userEvent.click(screen.getByLabelText(/I’ve saved my recovery code/))
      expect(go).toBeEnabled()
    })

    it('refuses mismatched passwords before asking the server', async () => {
      const fetchMock = server({
        '/api/desktop/status': () => json(200, { setup_required: true }),
      })
      arriveAt('/desktop-signin#code=launch-123')

      render(<DesktopSignInPage />)

      await screen.findByRole('heading', { name: 'Set up your books' })
      await fill('Your full name', 'Pat Owner')
      await fill('Email', 'pat@hotel.test')
      await fill('Password', 'correct horse battery')
      await fill('Type the password again', 'correct horse batter')
      await userEvent.click(screen.getByRole('button', { name: 'Set up my books' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('don’t match')
      expect(fetchMock.mock.calls.map(([u]) => u)).toEqual(['/api/desktop/status'])
    })

    it('a session left in the browser by an earlier install never gets in the way', async () => {
      // Same address, new data: a stored, unexpired token from the old
      // install. Following it would lose the launch code to a refusal.
      getUser.mockResolvedValue({ expired: false })
      server({ '/api/desktop/status': () => json(200, { setup_required: true }) })
      arriveAt('/desktop-signin#code=launch-123')

      render(<DesktopSignInPage />)

      expect(await screen.findByRole('heading', { name: 'Set up your books' })).toBeInTheDocument()
      expect(clearDesktopSession).toHaveBeenCalled()
    })

    it('without the launch code, says how to open it from the tray — and offers no form', async () => {
      server({ '/api/desktop/status': () => json(200, { setup_required: true }) })
      arriveAt('/desktop-signin')

      render(<DesktopSignInPage />)

      expect(
        await screen.findByRole('heading', { name: 'Welcome to Open Hospitality' }),
      ).toBeInTheDocument()
      expect(screen.getByText(/Open my books/)).toBeInTheDocument()
      expect(screen.queryByLabelText('Password')).toBeNull()
    })
  })

  describe('sign in', () => {
    it('trades an email and password for a session', async () => {
      const fetchMock = server({
        '/api/desktop/status': () => json(200, { setup_required: false }),
        '/api/desktop/signin': () => json(200, { ...TOKEN, recovery_code: null }),
      })
      arriveAt('/desktop-signin#code=spent-launch-code')

      render(<DesktopSignInPage />)

      await screen.findByRole('heading', { name: 'Sign in' })
      await fill('Email', 'pat@hotel.test')
      await fill('Password', 'correct horse battery')
      await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      await waitFor(() => expect(storeDesktopSession).toHaveBeenCalledWith('tok', 60))
      expect(bodyOf(fetchMock, '/api/desktop/signin')).toMatchObject({
        login: 'pat@hotel.test',
        password: 'correct horse battery',
      })
      expect(typeof bodyOf(fetchMock, '/api/desktop/signin').device_label).toBe('string')
      expect(window.location.hash).toBe('')
    })

    it('shows the server’s refusal, which names the next step', async () => {
      server({
        '/api/desktop/status': () => json(200, { setup_required: false }),
        '/api/desktop/signin': () =>
          json(401, { detail: 'That email and password don’t match. Use your recovery code.' }),
      })
      arriveAt('/desktop-signin')

      render(<DesktopSignInPage />)

      await screen.findByRole('heading', { name: 'Sign in' })
      await fill('Email', 'pat@hotel.test')
      await fill('Password', 'wrong password here')
      await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      expect(await screen.findByRole('alert')).toHaveTextContent('Use your recovery code.')
      expect(storeDesktopSession).not.toHaveBeenCalled()
      // The form stays usable for the next try.
      expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
    })

    it('says so after signing out', async () => {
      server({ '/api/desktop/status': () => json(200, { setup_required: false }) })
      arriveAt('/desktop-signin?signed-out=1')

      render(<DesktopSignInPage />)

      expect(await screen.findByRole('status')).toHaveTextContent('You’re signed out.')
    })

    it('an already signed-in browser goes straight to the books', async () => {
      getUser.mockResolvedValue({ expired: false })
      const fetchMock = server({ '/api/desktop/status': () => json(200, { setup_required: false }) })
      arriveAt('/desktop-signin#code=launch-123')

      render(<DesktopSignInPage />)

      await waitFor(() => expect(getUser).toHaveBeenCalled())
      // Only the one question; no sign-in form is shown or sent.
      expect(fetchMock.mock.calls.map(([u]) => u)).toEqual(['/api/desktop/status'])
      expect(screen.queryByRole('heading', { name: 'Sign in' })).toBeNull()
      expect(clearDesktopSession).not.toHaveBeenCalled()
    })
  })

  it('recovery sets a new password and replaces the recovery code', async () => {
    const fetchMock = server({
      '/api/desktop/status': () => json(200, { setup_required: false }),
      '/api/desktop/recover': () =>
        json(200, { ...TOKEN, recovery_code: 'NEWCO-DENEW-CODEN-EWCOD-ENEW0' }),
    })
    arriveAt('/desktop-signin')

    render(<DesktopSignInPage />)

    await userEvent.click(
      await screen.findByRole('button', { name: /Forgot your password\? Use your recovery code/ }),
    )
    await fill('Email', 'pat@hotel.test')
    await fill('Recovery code', 'abcde fghjk mnpqr stvwx yz012')
    await fill('New password', 'a brand new passphrase')
    await fill('Type the password again', 'a brand new passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Set my new password' }))

    expect(await screen.findByLabelText('Recovery code')).toHaveTextContent(
      'NEWCO-DENEW-CODEN-EWCOD-ENEW0',
    )
    expect(screen.getByText(/no longer works/)).toBeInTheDocument()
    expect(bodyOf(fetchMock, '/api/desktop/recover')).toMatchObject({
      login: 'pat@hotel.test',
      recovery_code: 'abcde fghjk mnpqr stvwx yz012',
      new_password: 'a brand new passphrase',
    })
  })

  it('a set-up code from the owner sets a new person’s password and signs them in', async () => {
    const fetchMock = server({
      '/api/desktop/status': () => json(200, { setup_required: false }),
      '/api/desktop/setup-code': () => json(200, { ...TOKEN, recovery_code: null }),
    })
    arriveAt('/desktop-signin')

    render(<DesktopSignInPage />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Have a set-up code from the owner?' }),
    )
    await fill('Email', 'sam@hotel.test')
    await fill('Set-up code', 'ABCD-EFGH')
    await fill('New password', 'sams own passphrase')
    await fill('Type the password again', 'sams own passphrase')
    await userEvent.click(screen.getByRole('button', { name: 'Save my password' }))

    await waitFor(() => expect(storeDesktopSession).toHaveBeenCalledWith('tok', 60))
    expect(bodyOf(fetchMock, '/api/desktop/setup-code')).toMatchObject({
      login: 'sam@hotel.test',
      code: 'ABCD-EFGH',
      new_password: 'sams own passphrase',
    })
  })

  it('when the local server doesn’t answer, says how to start it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    arriveAt('/desktop-signin')

    render(<DesktopSignInPage />)

    expect(
      await screen.findByRole('heading', { name: 'Open Hospitality isn’t answering' }),
    ).toBeInTheDocument()
  })
})
