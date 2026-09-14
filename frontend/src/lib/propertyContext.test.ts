import { describe, expect, it } from 'vitest'

import type { WelcomeState } from '../api/desktop'
import { withEveryHotel } from './propertyContext'
import { HISJ_PROPERTY } from '../test/fixtures'

const WELCOME: WelcomeState = {
  finished: true, group_name: 'G', group_named: true, backup_folder_set: true,
  pms_choices: [], jurisdictions: [],
  properties: [
    { property_id: 'HISJ', name: 'Holiday Inn San Jose', pms_source: 'OPERA',
      ownership_entity: null, has_fiscal_calendar: true, has_rooms: true },
    { property_id: 'NEW1', name: 'Harbour View', pms_source: 'SKYTOUCH',
      ownership_entity: 'Harbour LLC', has_fiscal_calendar: true, has_rooms: false },
  ],
}

describe('withEveryHotel', () => {
  it('adds a hotel the owner set up but that has no reports yet', () => {
    const out = withEveryHotel([HISJ_PROPERTY], WELCOME)
    expect(out?.map((p) => p.property_id)).toEqual(['HISJ', 'NEW1'])
    const added = out![1]!
    expect(added.name).toBe('Harbour View')
    expect(added.pms_source).toBe('SKYTOUCH')
    expect(added.first_date).toBe(added.last_date)
  })

  it('changes nothing on a hosted deployment, or before the lists have loaded', () => {
    expect(withEveryHotel([HISJ_PROPERTY], null)).toEqual([HISJ_PROPERTY])
    expect(withEveryHotel(undefined, WELCOME)).toBeUndefined()
  })
})
