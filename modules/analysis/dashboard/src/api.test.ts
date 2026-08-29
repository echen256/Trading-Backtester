import { afterEach, describe, expect, it, vi } from 'vitest'

import { listDatasets } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('dashboard API errors', () => {
  it('explains an empty proxy response instead of throwing a JSON parser error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', {
      status: 502,
      statusText: 'Bad Gateway',
    })))

    await expect(listDatasets()).rejects.toThrow(
      'Empty response from /api/datasets (502 Bad Gateway). The dashboard API may not be running',
    )
  })

  it('identifies non-JSON responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<!doctype html>', {
      status: 200,
      headers: { 'content-type': 'text/html' },
    })))

    await expect(listDatasets()).rejects.toThrow(
      'Expected JSON from /api/datasets, received text/html (200)',
    )
  })
})
