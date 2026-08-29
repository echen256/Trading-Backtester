import type { Bar, BarsResponse } from './types'

/** Expand the API's columnar wire format into chart-native rows. */
export function barsFromResponse(response: BarsResponse | null): Bar[] {
  if (!response) return []
  return response.bars.time.map((time, index) => ({
    time,
    open: response.bars.open[index],
    high: response.bars.high[index],
    low: response.bars.low[index],
    close: response.bars.close[index],
    volume: response.bars.volume[index],
  }))
}
