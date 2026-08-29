import type { BarsResponse, DatasetMetadata, StudyManifest, StudySummary, TpoProfileResponse } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = await response.text()
  if (!body.trim()) {
    const hint = response.status >= 500
      ? ' The dashboard API may not be running; use `npm run dev` to start both services.'
      : ''
    throw new Error(`Empty response from ${path} (${response.status} ${response.statusText}).${hint}`)
  }
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(body) as Record<string, unknown>
  } catch {
    const contentType = response.headers.get('content-type') || 'unknown content type'
    throw new Error(`Expected JSON from ${path}, received ${contentType} (${response.status}).`)
  }
  if (!response.ok) {
    throw new Error(typeof payload.error === 'string' ? payload.error : `Request failed (${response.status})`)
  }
  return payload as T
}

export async function listDatasets(): Promise<DatasetMetadata[]> {
  return (await request<{ datasets: DatasetMetadata[] }>('/api/datasets')).datasets
}

export async function listStudies(): Promise<StudySummary[]> {
  return (await request<{ studies: StudySummary[] }>('/api/studies')).studies
}

export function getStudy(runId: string): Promise<StudyManifest> {
  return request(`/api/studies/${encodeURIComponent(runId)}`)
}

export function getBars(datasetId: string, from: string, to: string, maxBars = 15_000): Promise<BarsResponse> {
  const query = new URLSearchParams({ from, to, maxBars: String(maxBars) })
  return request(`/api/datasets/${encodeURIComponent(datasetId)}/bars?${query}`)
}

export function getTpoProfile(datasetId: string, at: string, signal?: AbortSignal): Promise<TpoProfileResponse> {
  const query = new URLSearchParams({ at })
  return request(`/api/datasets/${encodeURIComponent(datasetId)}/tpo?${query}`, { signal })
}

export async function importDataset(payload: Record<string, unknown>): Promise<DatasetMetadata> {
  return request('/api/datasets/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
