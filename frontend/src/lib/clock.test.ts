import { describe, expect, it } from 'vitest'

import { parseClock, shiftText, to12 } from './clock'

describe('clock times the way people say them', () => {
  it('reads what an owner types', () => {
    expect(parseClock('7am')).toBe('07:00')
    expect(parseClock('7 a.m.')).toBe('07:00')
    expect(parseClock('3:30 pm')).toBe('15:30')
    expect(parseClock('3p')).toBe('15:00')
    expect(parseClock('12am')).toBe('00:00')
    expect(parseClock('12 pm')).toBe('12:00')
    expect(parseClock('noon')).toBe('12:00')
    expect(parseClock('midnight')).toBe('00:00')
    // No AM/PM: the 24-hour clock, as a night auditor writes "23".
    expect(parseClock('7')).toBe('07:00')
    expect(parseClock('15:00')).toBe('15:00')
    expect(parseClock('2300')).toBe('23:00')
  })

  it('refuses what is not a time', () => {
    for (const bad of ['', 'seven', '13pm', '25:00', '7:75', '0am']) {
      expect(parseClock(bad), bad).toBeNull()
    }
  })

  it('shows the server clock the way it is read', () => {
    expect(to12('07:00')).toBe('7:00 AM')
    expect(to12('15:30')).toBe('3:30 PM')
    expect(to12('00:00')).toBe('12:00 AM')
    expect(to12('12:00')).toBe('12:00 PM')
  })

  it('round-trips, so an unchanged field sends the same time back', () => {
    for (const t of ['00:00', '07:00', '12:00', '15:30', '23:45']) {
      expect(parseClock(to12(t))).toBe(t)
    }
  })

  it('describes a shift as the rota prints it', () => {
    expect(shiftText('07:00', '15:00', false)).toBe('7:00 AM – 3:00 PM')
    expect(shiftText('23:00', '07:00', true)).toBe('11:00 PM – 7:00 AM (+1)')
    expect(shiftText('09:00', '15:00', false, true)).toBe('9:00 AM – Done')
  })
})
