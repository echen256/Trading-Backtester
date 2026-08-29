import { describe, expect, it } from 'vitest'

import { clampTimelineEnd, timelineWindow } from './timeline'

describe('chart timeline navigation', () => {
  it('opens on the latest fixed-size window', () => {
    expect(timelineWindow(1_000, null, 200)).toMatchObject({
      start: 800,
      end: 999,
      size: 200,
      minimumEnd: 199,
      maximumEnd: 999,
      canMoveBackward: true,
      canMoveForward: false,
    })
  })

  it('clamps navigation at the oldest and latest loaded bars', () => {
    expect(clampTimelineEnd(1_000, -50, 200)).toBe(199)
    expect(clampTimelineEnd(1_000, 4_000, 200)).toBe(999)
    expect(timelineWindow(1_000, 450, 200)).toMatchObject({
      start: 251,
      end: 450,
      canMoveBackward: true,
      canMoveForward: true,
    })
  })

  it('shows all bars and disables movement for short datasets', () => {
    expect(timelineWindow(80, null, 240)).toEqual({
      start: 0,
      end: 79,
      size: 80,
      minimumEnd: 79,
      maximumEnd: 79,
      canMoveBackward: false,
      canMoveForward: false,
    })
  })
})
