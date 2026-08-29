export const DEFAULT_TIMELINE_BARS = 240

export interface TimelineWindow {
  start: number
  end: number
  size: number
  minimumEnd: number
  maximumEnd: number
  canMoveBackward: boolean
  canMoveForward: boolean
}

export function clampTimelineEnd(
  barCount: number,
  requestedEnd: number,
  requestedSize = DEFAULT_TIMELINE_BARS,
): number {
  if (barCount <= 0) return 0
  const size = Math.min(Math.max(1, requestedSize), barCount)
  return Math.min(barCount - 1, Math.max(size - 1, Math.round(requestedEnd)))
}

export function timelineWindow(
  barCount: number,
  requestedEnd: number | null,
  requestedSize = DEFAULT_TIMELINE_BARS,
): TimelineWindow {
  if (barCount <= 0) {
    return {
      start: 0, end: 0, size: 0, minimumEnd: 0, maximumEnd: 0,
      canMoveBackward: false, canMoveForward: false,
    }
  }
  const size = Math.min(Math.max(1, requestedSize), barCount)
  const minimumEnd = size - 1
  const maximumEnd = barCount - 1
  const end = requestedEnd === null
    ? maximumEnd
    : clampTimelineEnd(barCount, requestedEnd, size)
  return {
    start: end - size + 1,
    end,
    size,
    minimumEnd,
    maximumEnd,
    canMoveBackward: end > minimumEnd,
    canMoveForward: end < maximumEnd,
  }
}
