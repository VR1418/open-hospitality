import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  BackupStatus,
  DesktopModule,
  ModulesResponse,
  NewHotel,
  WelcomeState,
} from '../api/desktop'
import WelcomePage from './WelcomePage'

const getWelcome = vi.fn<() => Promise<WelcomeState | null>>()
const nameGroup = vi.fn<(name: string) => Promise<void>>()
const addHotel = vi.fn<(body: NewHotel) => Promise<{ property_id: string; name: string }>>()
const finishWelcome = vi.fn<() => Promise<void>>()
const getModules = vi.fn<() => Promise<ModulesResponse | null>>()
const saveModules = vi.fn<(enabled: string[]) => Promise<ModulesResponse>>()
const waitForModules = vi.fn<(enabled: string[]) => Promise<void>>()
const getBackupStatus = vi.fn<() => Promise<BackupStatus | null>>()
const setBackupFolder = vi.fn<(folder: string) => Promise<BackupStatus>>()

vi.mock('../api/desktop', () => ({
  getWelcome: () => getWelcome(),
  nameGroup: (name: string) => nameGroup(name),
  addHotel: (body: NewHotel) => addHotel(body),
  finishWelcome: () => finishWelcome(),
  getModules: () => getModules(),
  saveModules: (enabled: string[]) => saveModules(enabled),
  waitForModules: (enabled: string[]) => waitForModules(enabled),
  getBackupStatus: () => getBackupStatus(),
  setBackupFolder: (folder: string) => setBackupFolder(folder),
}))

const NO_BACKUPS: BackupStatus = {
  folder: null, suggested_folder: 'C:\\Docs\\Backups',
  last_backup_at: null, last_file: null, armed: true, due: false, keep: 7, files: [],
}

const FRESH: WelcomeState = {
  finished: false,
  backup_folder_set: false,
  group_name: 'Pilot Hotel Group',
  group_named: false,
  properties: [],
  pms_choices: [
    { id: 'AUTOCLERK', name: 'AutoClerk' },
    { id: 'SKYTOUCH', name: 'choiceADVANTAGE' },
    { id: 'OPERA', name: 'Oracle OPERA' },
  ],
}

function mod(overrides: Partial<DesktopModule>): DesktopModule {
  return {
    id: 'x', name: 'X', summary: '', status: 'available', required: false, enabled: false,
    nav: [], limitations: [{ text: 'A limit.', workaround: null }], ...overrides,
  }
}

const MODULES: DesktopModule[] = [
  mod({ id: 'accounting', name: 'Accounting & Reporting', required: true, enabled: true }),
  mod({ id: 'payroll', name: 'Payroll & People' }),
  mod({ id: 'utilities', name: 'Hotel Management Utilities', status: 'coming_soon' }),
]

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <WelcomePage />
    </QueryClientProvider>,
  )
}

async function type(label: string, value: string) {
  await userEvent.type(screen.getByLabelText(label), value)
}

describe('WelcomePage', () => {
  beforeEach(() => {
    getWelcome.mockReset().mockResolvedValue(FRESH)
    nameGroup.mockReset().mockResolvedValue(undefined)
    addHotel.mockReset().mockResolvedValue({ property_id: 'RI', name: 'Redstone Inn' })
    finishWelcome.mockReset().mockResolvedValue(undefined)
    getModules.mockReset().mockResolvedValue({ modules: MODULES, reloading: false })
    saveModules.mockReset().mockResolvedValue({ modules: MODULES, reloading: true })
    waitForModules.mockReset().mockResolvedValue(undefined)
    getBackupStatus.mockReset().mockResolvedValue(NO_BACKUPS)
    setBackupFolder.mockReset().mockResolvedValue({ ...NO_BACKUPS, folder: 'D:\\Sync' })
  })

  it('walks a new owner from hotel group to modules', async () => {
    renderPage()

    // 1. Hotel group.
    expect(await screen.findByText('Step 1 of 5')).toBeInTheDocument()
    // The founding placeholder name is never offered as the owner's.
    expect(screen.getByLabelText('Your hotel group’s name')).toHaveValue('')
    await type('Your hotel group’s name', 'Redstone Hotels')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(nameGroup).toHaveBeenCalledWith('Redstone Hotels')

    // 2. The hotel. Nothing is saved yet: it goes with its fiscal year.
    expect(await screen.findByText('Step 2 of 5')).toBeInTheDocument()
    await type('Hotel name', 'Redstone Inn')
    await userEvent.selectOptions(screen.getByLabelText('Front-desk system (PMS)'), 'SKYTOUCH')
    await type('Rooms you can sell', '60')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(addHotel).not.toHaveBeenCalled()

    // 3. Fiscal year, then one save for the whole hotel.
    expect(await screen.findByRole('heading', { name: 'Redstone Inn’s financial year' })).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText(/4-4-5 weeks/))
    await userEvent.selectOptions(screen.getByLabelText('The financial year starts in'), '4')
    await userEvent.selectOptions(screen.getByLabelText('Weeks start on'), '6')
    await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }))
    expect(addHotel).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Redstone Inn',
        // Left blank, the name on reports is the hotel's name.
        report_name: 'Redstone Inn',
        pms_source: 'SKYTOUCH',
        total_rooms: 60,
        fiscal: { calendar_type: '445', fiscal_year_start_month: 4, week_start_weekday: 6 },
      }),
    )

    // 4. Where the backup goes — asked during setup, not left to settings.
    expect(
      await screen.findByRole('heading', { name: 'Keep a copy of your books' }),
    ).toBeInTheDocument()
    const folder = screen.getByLabelText('Backup folder')
    expect(folder).toHaveValue('C:\\Docs\\Backups') // the suggestion, ready to accept
    await userEvent.clear(folder)
    await userEvent.type(folder, 'D:\\OneDrive\\Books')
    await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }))
    expect(setBackupFolder).toHaveBeenCalledWith('D:\\OneDrive\\Books')

    // 5. Modules: the core is always on, the unbuilt can't be chosen.
    expect(await screen.findByText('Step 5 of 5')).toBeInTheDocument()
    const accounting = screen.getByRole('group', { name: 'Accounting & Reporting' })
    expect(within(accounting).getByRole('checkbox')).toBeDisabled()
    expect(
      within(screen.getByRole('group', { name: 'Hotel Management Utilities' })).getByRole('checkbox'),
    ).toBeDisabled()
    await userEvent.click(
      within(screen.getByRole('group', { name: 'Payroll & People' })).getByRole('checkbox'),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Finish' }))

    expect(await screen.findByRole('heading', { name: 'You’re set up' })).toBeInTheDocument()
    expect(finishWelcome).toHaveBeenCalled()
    expect(saveModules).toHaveBeenCalledWith(['accounting', 'payroll'])
    expect(waitForModules).toHaveBeenCalled()
  })

  it('says so, and goes no further, when the hotel’s PMS is one it can’t read', async () => {
    getWelcome.mockResolvedValue({ ...FRESH, group_named: true, group_name: 'Redstone Hotels' })
    renderPage()

    expect(await screen.findByText('Step 2 of 5')).toBeInTheDocument()
    await type('Hotel name', 'Redstone Inn')
    await type('Rooms you can sell', '60')
    await userEvent.selectOptions(screen.getByLabelText('Front-desk system (PMS)'), 'other')

    expect(screen.getByRole('status')).toHaveTextContent('can’t read your reports yet')
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('shows the server’s refusal and keeps the answers', async () => {
    getWelcome.mockResolvedValue({ ...FRESH, group_named: true, group_name: 'Redstone Hotels' })
    addHotel.mockRejectedValue(new Error('Reports that say “REDSTONE” already belong to RI.'))
    renderPage()

    await screen.findByText('Step 2 of 5')
    await type('Hotel name', 'Redstone Inn')
    await type('Rooms you can sell', '60')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save and continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('already belong to RI')
    expect(screen.getByText('Step 3 of 5')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByLabelText('Hotel name')).toHaveValue('Redstone Inn')
  })

  it('an owner with a hotel but no backup folder is asked for one', async () => {
    getWelcome.mockResolvedValue({
      ...FRESH,
      group_named: true,
      group_name: 'Redstone Hotels',
      backup_folder_set: false,
      properties: [
        { property_id: 'RI', name: 'Redstone Inn', pms_source: 'SKYTOUCH',
          has_fiscal_calendar: true, has_rooms: true },
      ],
    })
    renderPage()

    expect(
      await screen.findByRole('heading', { name: 'Keep a copy of your books' }),
    ).toBeInTheDocument()
    // Skipping is allowed — nagging is the Overview's job, not a locked door.
    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    expect(await screen.findByText('Step 5 of 5')).toBeInTheDocument()
    expect(setBackupFolder).not.toHaveBeenCalled()
  })

  it('“Add a hotel” reopens just the hotel steps on a finished install', async () => {
    window.history.replaceState(null, '', '/welcome?add=hotel')
    getWelcome.mockResolvedValue({
      ...FRESH,
      finished: true,
      group_named: true,
      group_name: 'Redstone Hotels',
      properties: [
        { property_id: 'RI', name: 'Redstone Inn', pms_source: 'SKYTOUCH',
          has_fiscal_calendar: true, has_rooms: true },
      ],
    })
    try {
      renderPage()

      // Straight to the form: no "you already have" list, no step numbers.
      expect(await screen.findByRole('heading', { name: 'Add a hotel' })).toBeInTheDocument()
      expect(screen.queryByText(/Step \d of 5/)).toBeNull()
      expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/overview')
      await type('Hotel name', 'Harbour View')
      await userEvent.selectOptions(screen.getByLabelText('Front-desk system (PMS)'), 'OPERA')
      await type('Rooms you can sell', '120')
      await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Save and continue' }))

      expect(addHotel).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Harbour View', pms_source: 'OPERA', total_rooms: 120 }),
      )
      // It never asks the module question again.
      expect(finishWelcome).not.toHaveBeenCalled()
    } finally {
      window.history.replaceState(null, '', '/')
    }
  })

  it('an owner who left half-way picks up at the first unanswered question', async () => {
    getWelcome.mockResolvedValue({
      ...FRESH,
      group_named: true,
      group_name: 'Redstone Hotels',
      backup_folder_set: true,
      properties: [
        { property_id: 'RI', name: 'Redstone Inn', pms_source: 'SKYTOUCH',
          has_fiscal_calendar: true, has_rooms: true },
      ],
    })
    renderPage()

    expect(await screen.findByText('Step 5 of 5')).toBeInTheDocument()
    expect(nameGroup).not.toHaveBeenCalled()
  })
})
