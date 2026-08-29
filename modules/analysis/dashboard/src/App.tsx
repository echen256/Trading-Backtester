import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getBars, getStudy, importDataset, listDatasets, listStudies } from './api'
import { ChartWorkbench } from './chart/ChartWorkbench'
import { barsFromResponse } from './normalize'
import type {
  BarsResponse, DatasetMetadata, StudyManifest, StudyPoint, StudySummary, StudyView,
} from './types'

function intervalLabel(seconds: number): string {
  if (seconds % 604800 === 0) return `${seconds / 604800}w`
  if (seconds % 86400 === 0) return `${seconds / 86400}d`
  if (seconds % 3600 === 0) return `${seconds / 3600}h`
  if (seconds % 60 === 0) return `${seconds / 60}m`
  return `${seconds}s`
}

function dateInput(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : ''
}

function displayValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function App() {
  const initial = useMemo(() => new URLSearchParams(window.location.search), [])
  const [datasets, setDatasets] = useState<DatasetMetadata[]>([])
  const [studies, setStudies] = useState<StudySummary[]>([])
  const [datasetId, setDatasetId] = useState(initial.get('dataset') ?? '')
  const [studyRunId, setStudyRunId] = useState(initial.get('study') ?? '')
  const [manifest, setManifest] = useState<StudyManifest | null>(null)
  const [viewId, setViewId] = useState(initial.get('view') ?? '')
  const [from, setFrom] = useState(initial.get('from') ?? '')
  const [to, setTo] = useState(initial.get('to') ?? '')
  const [barsResponse, setBarsResponse] = useState<BarsResponse | null>(null)
  const [visibleGroups, setVisibleGroups] = useState<Set<string>>(new Set())
  const [selectedPoint, setSelectedPoint] = useState<StudyPoint | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [importPath, setImportPath] = useState('')
  const [importSymbol, setImportSymbol] = useState('')
  const [importAssetClass, setImportAssetClass] = useState('')
  const requestSequence = useRef(0)

  const selectedDataset = datasets.find((dataset) => dataset.id === datasetId) ?? null
  const selectedView: StudyView | null = manifest?.views.find((view) => view.id === viewId) ?? manifest?.views[0] ?? null
  const activeChart = selectedView?.dataset_id === datasetId ? selectedView.chart : null
  const bars = useMemo(() => barsFromResponse(barsResponse), [barsResponse])

  const refreshCatalog = useCallback(async () => {
    const [datasetItems, studyItems] = await Promise.all([listDatasets(), listStudies()])
    setDatasets(datasetItems)
    setStudies(studyItems)
    setDatasetId((current) => current || datasetItems[0]?.id || '')
  }, [])

  useEffect(() => {
    refreshCatalog().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  }, [refreshCatalog])

  useEffect(() => {
    if (!selectedDataset) return
    setFrom((current) => current || dateInput(selectedDataset.quality.first_timestamp))
    setTo((current) => current || dateInput(selectedDataset.quality.last_timestamp))
  }, [selectedDataset])

  useEffect(() => {
    if (!datasetId || !from || !to) return
    const sequence = ++requestSequence.current
    setLoading(true)
    setError(null)
    getBars(datasetId, `${from}T00:00:00Z`, `${to}T23:59:59.999Z`)
      .then((response) => {
        if (sequence === requestSequence.current) setBarsResponse(response)
      })
      .catch((reason: unknown) => {
        if (sequence === requestSequence.current) setError(reason instanceof Error ? reason.message : String(reason))
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false)
      })
  }, [datasetId, from, to])

  useEffect(() => {
    if (!studyRunId) {
      setManifest(null)
      setViewId('')
      return
    }
    getStudy(studyRunId)
      .then((value) => {
        setManifest(value)
        const requested = value.views.find((view) => view.id === viewId)
        const view = requested ?? value.views[0]
        if (view) {
          setViewId(view.id)
          setDatasetId(view.dataset_id)
          setFrom(dateInput(view.default_start))
          setTo(dateInput(view.default_end))
        } else {
          setViewId('')
        }
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  }, [studyRunId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedView) {
      setVisibleGroups(new Set())
      return
    }
    setVisibleGroups(new Set(selectedView.chart.groups.filter((group) => group.visible !== false).map((group) => group.id)))
    setSelectedPoint(null)
  }, [selectedView])

  useEffect(() => {
    const query = new URLSearchParams()
    if (datasetId) query.set('dataset', datasetId)
    if (studyRunId) query.set('study', studyRunId)
    if (viewId) query.set('view', viewId)
    if (from) query.set('from', from)
    if (to) query.set('to', to)
    window.history.replaceState(null, '', `${window.location.pathname}?${query}`)
  }, [datasetId, studyRunId, viewId, from, to])

  const handleDatasetChange = (nextId: string) => {
    const dataset = datasets.find((item) => item.id === nextId)
    setDatasetId(nextId)
    setFrom(dateInput(dataset?.quality.first_timestamp))
    setTo(dateInput(dataset?.quality.last_timestamp))
    if (!manifest?.views.some((view) => view.dataset_id === nextId)) {
      setStudyRunId('')
    }
    setSelectedPoint(null)
  }

  const handleViewChange = (nextId: string) => {
    const view = manifest?.views.find((candidate) => candidate.id === nextId)
    setViewId(nextId)
    if (view) {
      setDatasetId(view.dataset_id)
      setFrom(dateInput(view.default_start))
      setTo(dateInput(view.default_end))
    }
  }

  const handlePointSelect = useCallback((point: StudyPoint) => setSelectedPoint(point), [])

  const handleImport = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      setLoading(true)
      setError(null)
      const payload: Record<string, unknown> = { path: importPath }
      if (importSymbol.trim()) payload.symbol = importSymbol.trim().toUpperCase()
      if (importAssetClass) payload.asset_class = importAssetClass
      const imported = await importDataset(payload)
      await refreshCatalog()
      setDatasetId(imported.id)
      setFrom(dateInput(imported.quality.first_timestamp))
      setTo(dateInput(imported.quality.last_timestamp))
      setShowImport(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">TA</div>
          <div><h1>Trading Analysis</h1><p>Canonical market-data and study workbench</p></div>
        </div>
        <div className="topbar-actions">
          <button className="secondary" onClick={() => setShowImport((value) => !value)}>Import data</button>
          <button className="secondary" onClick={() => refreshCatalog()}>Refresh catalog</button>
          <span className={`connection ${error ? 'error' : ''}`}>{error ? 'Attention' : 'Local catalog'}</span>
        </div>
      </header>

      {showImport && (
        <form className="import-panel" onSubmit={handleImport}>
          <label>Local CSV, CSV.gz, or Parquet path<input value={importPath} onChange={(event) => setImportPath(event.target.value)} required placeholder="/Users/.../BTCUSDT_5m.csv.gz" /></label>
          <label>Symbol override<input value={importSymbol} onChange={(event) => setImportSymbol(event.target.value)} placeholder="Optional" /></label>
          <label>Asset class<select value={importAssetClass} onChange={(event) => setImportAssetClass(event.target.value)}><option value="">Infer</option><option value="stock">Stock</option><option value="crypto">Crypto</option><option value="index">Index</option><option value="option">Option</option><option value="forex">Forex</option></select></label>
          <button type="submit" disabled={loading}>Normalize and catalog</button>
        </form>
      )}

      {error && <div className="error-banner"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div>}

      <div className="workspace-grid">
        <aside className="sidebar">
          <section>
            <div className="section-title"><span>Market data</span><strong>{datasets.length}</strong></div>
            <label className="control-label">Dataset
              <select value={datasetId} onChange={(event) => handleDatasetChange(event.target.value)}>
                {!datasets.length && <option value="">No datasets imported</option>}
                {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.symbol} · {intervalLabel(dataset.interval_seconds)} · {dataset.venue}</option>)}
              </select>
            </label>
            {selectedDataset && <DatasetCard dataset={selectedDataset} />}
          </section>

          <section>
            <div className="section-title"><span>Study</span><strong>{studies.length}</strong></div>
            <label className="control-label">Study run
              <select value={studyRunId} onChange={(event) => setStudyRunId(event.target.value)}>
                <option value="">Price only</option>
                {studies.map((study) => <option key={study.id} value={study.id}>{study.study_name} · {new Date(study.generated_at).toLocaleDateString()}</option>)}
              </select>
            </label>
            {manifest && manifest.views.length > 1 && (
              <label className="control-label">View
                <select value={selectedView?.id ?? ''} onChange={(event) => handleViewChange(event.target.value)}>
                  {manifest.views.map((view) => <option key={view.id} value={view.id}>{view.label}</option>)}
                </select>
              </label>
            )}
            {activeChart?.groups.map((group) => (
              <label className="group-toggle" key={group.id}>
                <input type="checkbox" checked={visibleGroups.has(group.id)} onChange={() => setVisibleGroups((current) => {
                  const next = new Set(current)
                  if (next.has(group.id)) next.delete(group.id); else next.add(group.id)
                  return next
                })} />
                <i style={{ background: group.color ?? '#59c3ff' }} />
                <span>{group.label}</span>
              </label>
            ))}
          </section>
        </aside>

        <main className="main-workspace">
          <section className="chart-panel">
            <div className="chart-toolbar">
              <div>
                <h2>{selectedDataset?.symbol ?? 'No dataset'} <small>{selectedDataset ? intervalLabel(selectedDataset.interval_seconds) : ''}</small></h2>
                <p>{manifest ? `${manifest.study.name} · ${selectedView?.label ?? ''}` : 'Price and volume'}</p>
              </div>
              <div className="range-controls">
                <label>From<input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
                <label>To<input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
              </div>
              <div className="bar-status">
                {loading ? 'Loading…' : `${barsResponse?.count.toLocaleString() ?? 0} bars`}
                {barsResponse?.aggregated && <span>aggregated to {intervalLabel(barsResponse.response_interval_seconds)}</span>}
              </div>
            </div>
            <ChartWorkbench datasetId={datasetId} bars={bars} study={activeChart} visibleGroups={visibleGroups} selectedPointId={selectedPoint?.id} onPointSelect={handlePointSelect} />
          </section>

          <section className="results-grid">
            <div className="result-panel">
              <div className="section-title"><span>Study results</span><strong>{activeChart?.points.length ?? 0} events</strong></div>
              {selectedPoint ? <PointDetail point={selectedPoint} /> : <p className="empty-copy">Select a chart event or table row to inspect its metadata.</p>}
              {activeChart && <EventTable points={activeChart.points} selectedId={selectedPoint?.id} onSelect={setSelectedPoint} />}
            </div>
            <div className="result-panel">
              <div className="section-title"><span>Run information</span><strong>{manifest?.run.status ?? 'data'}</strong></div>
              {manifest ? <RunDetails manifest={manifest} /> : <DataQuality dataset={selectedDataset} />}
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}

function DatasetCard({ dataset }: { dataset: DatasetMetadata }) {
  return <div className="dataset-card">
    <div><span>Asset</span><strong>{dataset.asset_class}</strong></div>
    <div><span>Rows</span><strong>{dataset.quality.row_count.toLocaleString()}</strong></div>
    <div><span>Source</span><strong>{dataset.source.provider}</strong></div>
    <div><span>Gaps</span><strong className={dataset.quality.missing_intervals ? 'warning-text' : ''}>{dataset.quality.missing_intervals}</strong></div>
    <p title={dataset.source.path}>{dataset.source.path}</p>
  </div>
}

function DataQuality({ dataset }: { dataset: DatasetMetadata | null }) {
  if (!dataset) return <p className="empty-copy">Import a dataset to begin.</p>
  return <div className="details-list">
    <div><span>First bar</span><strong>{dataset.quality.first_timestamp}</strong></div>
    <div><span>Last bar</span><strong>{dataset.quality.last_timestamp}</strong></div>
    <div><span>Duplicates removed</span><strong>{dataset.quality.duplicates_removed}</strong></div>
    {dataset.quality.warnings.map((warning) => <p className="warning-copy" key={warning}>{warning}</p>)}
  </div>
}

function PointDetail({ point }: { point: StudyPoint }) {
  return <div className="point-detail">
    <div><span>{point.role ?? 'event'}</span><h3>{point.label || point.id}</h3><p>{new Date(point.time).toLocaleString()} · {point.value.toLocaleString()}</p></div>
    <dl>{Object.entries(point.metadata ?? {}).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{displayValue(value)}</dd></div>)}</dl>
  </div>
}

function EventTable({ points, selectedId, onSelect }: { points: StudyPoint[]; selectedId?: string; onSelect: (point: StudyPoint) => void }) {
  if (!points.length) return null
  return <div className="table-scroll"><table><thead><tr><th>Time</th><th>Event</th><th>Group</th><th>Value</th></tr></thead><tbody>
    {points.slice(0, 1000).map((point) => <tr key={point.id} className={point.id === selectedId ? 'selected' : ''} onClick={() => onSelect(point)}><td>{point.time.slice(0, 16).replace('T', ' ')}</td><td>{point.label || point.role || point.id}</td><td>{point.group}</td><td>{point.value.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td></tr>)}
  </tbody></table>{points.length > 1000 && <p className="table-note">Showing the first 1,000 of {points.length.toLocaleString()} events.</p>}</div>
}

function RunDetails({ manifest }: { manifest: StudyManifest }) {
  return <div className="run-details">
    <h3>{manifest.study.name} <small>v{manifest.study.version}</small></h3>
    <p>{manifest.study.description}</p>
    <div className="metric-grid">{manifest.metrics.map((metric, index) => {
      const entries = Object.entries(metric)
      const label = displayValue(metric.label ?? metric.name ?? entries[0]?.[0] ?? `Metric ${index + 1}`)
      const value = metric.value ?? entries.find(([key]) => !['label', 'name'].includes(key))?.[1]
      return <div className="metric" key={`${label}-${index}`}><span>{label}</span><strong>{displayValue(value)}</strong></div>
    })}</div>
    {manifest.tables.map((table, index) => <details key={table.id ?? index}><summary>{table.label ?? table.id ?? `Table ${index + 1}`} · {table.rows?.length ?? 0} rows</summary><GenericTable table={table} /></details>)}
    {Object.keys(manifest.resources).length > 0 && <div className="resource-list"><h4>Files</h4>{Object.entries(manifest.resources).map(([name, raw]) => {
      const resource = raw as { path?: string; media_type?: string; bytes?: number }
      const resourcePath = (resource.path ?? name).split('/').map(encodeURIComponent).join('/')
      return <a key={name} href={`/api/studies/${encodeURIComponent(manifest.run.id)}/resources/${resourcePath}`} target="_blank" rel="noreferrer"><span>{name}</span><small>{resource.media_type ?? 'file'} · {resource.bytes ? `${Math.ceil(resource.bytes / 1024).toLocaleString()} KB` : ''}</small></a>
    })}</div>}
    {manifest.methodology && <details><summary>Methodology</summary><p className="methodology">{manifest.methodology}</p></details>}
    <dl className="manifest-meta"><div><dt>Run</dt><dd>{manifest.run.id}</dd></div><div><dt>Generated</dt><dd>{new Date(manifest.run.generated_at).toLocaleString()}</dd></div><div><dt>Generator</dt><dd>{manifest.study.generator || 'unknown'}</dd></div></dl>
  </div>
}

function GenericTable({ table }: { table: StudyManifest['tables'][number] }) {
  const rows = table.rows ?? []
  const columns = table.columns ?? Object.keys(rows[0] ?? {})
  if (!rows.length) return <p className="empty-copy">No inline rows.</p>
  return <div className="table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 250).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div>
}
