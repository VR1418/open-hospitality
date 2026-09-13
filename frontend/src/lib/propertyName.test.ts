import { describe, expect, it } from 'vitest'

import type { PropertyInfo } from '../api/types'
import { propertyDisplayName, propertyLabel, titleCase } from './propertyName'

const HISJ: PropertyInfo = {
  property_id: 'HISJ',
  pms_source: 'OPERA',
  first_date: '2026-07-01',
  last_date: '2026-07-07',
  name: 'HOLIDAY INN & SUITES SAN JOSE',
}

describe('what an owner calls their hotel', () => {
  it('stops shouting the name the reports print', () => {
    expect(titleCase('REDSTONE TEST INN, TX')).toBe('Redstone Test Inn, Tx')
    expect(propertyDisplayName(HISJ)).toBe('Holiday Inn & Suites San Jose')
  })

  it('capitalises after a space, a bracket, a slash or a dash', () => {
    expect(titleCase('HAMPTON INN (DOWNTOWN)')).toBe('Hampton Inn (Downtown)')
    expect(titleCase('COURTYARD - NORTH/WEST')).toBe('Courtyard - North/West')
  })

  it('falls back to the code when the registry has no name', () => {
    expect(propertyDisplayName({ ...HISJ, name: null })).toBe('HISJ')
    expect(propertyLabel({ ...HISJ, name: null })).toBe('HISJ')
  })

  it('never shows the PMS identifier, which means nothing to the reader', () => {
    // The top bar used to read "HISJ — OPERA".
    expect(propertyLabel(HISJ)).toBe('Holiday Inn & Suites San Jose · HISJ')
    expect(propertyLabel(HISJ)).not.toContain('OPERA')
  })

  it('is nothing when no hotel is selected yet', () => {
    expect(propertyDisplayName(undefined)).toBeNull()
  })
})
