import { describe, expect, it } from 'vitest'

import { barsFromResponse } from './normalize'
import type { BarsResponse } from './types'

describe('barsFromResponse', () => {
  it('expands aligned columnar bars and preserves missing volume', () => {
    const response: BarsResponse = {
      dataset_id: 'test',
      symbol: 'BTCUSDT',
      native_interval_seconds: 300,
      response_interval_seconds: 300,
      aggregated: false,
      count: 2,
      bars: {
        time: ['2026-01-01T00:00:00Z', '2026-01-01T00:05:00Z'],
        open: [100, 101],
        high: [102, 103],
        low: [99, 100],
        close: [101, 102],
        volume: [12, null],
      },
    }

    expect(barsFromResponse(response)).toEqual([
      { time: '2026-01-01T00:00:00Z', open: 100, high: 102, low: 99, close: 101, volume: 12 },
      { time: '2026-01-01T00:05:00Z', open: 101, high: 103, low: 100, close: 102, volume: null },
    ])
  })

  it('returns no bars before the first response', () => {
    expect(barsFromResponse(null)).toEqual([])
  })
})
