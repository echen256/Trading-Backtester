// @vitest-environment jsdom

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getTpoProfile } from '../api'
import type { TpoProfileResponse } from '../types'
import { TpoProfile } from './TpoProfile'

vi.mock('../api', () => ({ getTpoProfile: vi.fn() }))

const PROFILE: TpoProfileResponse = {
  available: true,
  dataset_id: 'btc',
  symbol: 'BTCUSDT',
  asset_class: 'crypto',
  session_date: '2026-08-25',
  session_label: '00:00–24:00 UTC',
  session_timezone: 'UTC',
  session_start: '2026-08-25T00:00:00Z',
  session_end: '2026-08-26T00:00:00Z',
  profile_through: '2026-08-25T12:00:00Z',
  complete: false,
  period_minutes: 30,
  native_interval_seconds: 300,
  bar_count: 145,
  bracket_size: 100,
  total_tpos: 10,
  poc: 80_000,
  vah: 80_200,
  val: 79_800,
  ib_high: 80_100,
  ib_low: 79_700,
  session_high: 80_400,
  session_low: 79_600,
  levels: [
    { price: 80_100, count: 2, letters: ['A', 'B'], in_value_area: true, is_poc: false },
    { price: 80_000, count: 4, letters: ['A', 'B', 'C', 'D'], in_value_area: true, is_poc: true },
  ],
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('dynamic TPO profile', () => {
  it('renders a profile and requests a new one when the timeline moves', async () => {
    vi.mocked(getTpoProfile).mockResolvedValue(PROFILE)
    const view = render(<TpoProfile datasetId="btc" atTime="2026-08-25T12:00:00Z" />)

    expect(await screen.findByText('BTCUSDT · 2026-08-25')).toBeTruthy()
    expect(screen.getByText('Developing session')).toBeTruthy()
    expect(screen.getByText('A B C D')).toBeTruthy()
    expect(getTpoProfile).toHaveBeenCalledWith('btc', '2026-08-25T12:00:00Z', expect.any(AbortSignal))

    view.rerender(<TpoProfile datasetId="btc" atTime="2026-08-25T13:00:00Z" />)
    await waitFor(() => expect(getTpoProfile).toHaveBeenLastCalledWith(
      'btc', '2026-08-25T13:00:00Z', expect.any(AbortSignal),
    ))
  })
})
