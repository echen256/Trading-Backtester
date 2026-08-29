import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AreaSeries,
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type Logical,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Bar, ChartStudy, StudyPoint } from '../types'
import { TpoProfile } from './TpoProfile'
import { clampTimelineEnd, timelineWindow } from './timeline'

interface ChartWorkbenchProps {
  datasetId: string
  bars: Bar[]
  study?: ChartStudy | null
  visibleGroups: Set<string>
  selectedPointId?: string | null
  onPointSelect?: (point: StudyPoint) => void
}

const EMPTY_STUDY: ChartStudy = {
  schema_version: 'trading-chart-study/v2',
  groups: [],
  panels: [],
  points: [],
  links: [],
  spans: [],
  levels: [],
}

function asTime(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp
}

function colorWithOpacity(color: string, opacity: number): string {
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const alpha = Math.max(0, Math.min(255, Math.round(opacity * 255))).toString(16).padStart(2, '0')
    return `${color}${alpha}`
  }
  return color
}

function nearestBarTime(pointTime: string, bars: Bar[]): UTCTimestamp | null {
  if (!bars.length) return null
  const target = new Date(pointTime).getTime()
  let low = 0
  let high = bars.length - 1
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (new Date(bars[middle].time).getTime() < target) low = middle + 1
    else high = middle
  }
  const candidate = low
  const prior = Math.max(0, candidate - 1)
  const chosen = Math.abs(new Date(bars[prior].time).getTime() - target) <= Math.abs(new Date(bars[candidate].time).getTime() - target)
    ? prior
    : candidate
  return asTime(bars[chosen].time)
}

function nearestBarIndex(pointTime: string, bars: Bar[]): number | null {
  if (!bars.length) return null
  const target = new Date(pointTime).getTime()
  let low = 0
  let high = bars.length - 1
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (new Date(bars[middle].time).getTime() < target) low = middle + 1
    else high = middle
  }
  const prior = Math.max(0, low - 1)
  return Math.abs(new Date(bars[prior].time).getTime() - target) <= Math.abs(new Date(bars[low].time).getTime() - target)
    ? prior
    : low
}

function navigationLabel(value: string | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function markerShape(marker: string | undefined, role: string | undefined): SeriesMarker<Time>['shape'] {
  if (marker === 'square') return 'square'
  if (marker === 'circle' || marker === 'diamond' || marker === 'star' || marker === 'cross' || marker === 'x') return 'circle'
  if (marker === 'triangle-down' || role === 'exit' || role === 'target') return 'arrowDown'
  return 'arrowUp'
}

export function ChartWorkbench({ datasetId, bars, study, visibleGroups, selectedPointId, onPointSelect }: ChartWorkbenchProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [navigationEnd, setNavigationEnd] = useState<number | null>(null)
  const resolvedStudy = study ?? EMPTY_STUDY
  const timeline = useMemo(() => timelineWindow(bars.length, navigationEnd), [bars.length, navigationEnd])
  const eventPoints = useMemo(
    () => resolvedStudy.points.filter((point) => visibleGroups.has(point.group) && (point.pane ?? 'price') === 'price'),
    [resolvedStudy, visibleGroups],
  )

  useEffect(() => {
    setNavigationEnd(null)
  }, [bars])

  useEffect(() => {
    if (!selectedPointId) return
    const selected = resolvedStudy.points.find((point) => point.id === selectedPointId)
    if (!selected) return
    const index = nearestBarIndex(selected.time, bars)
    if (index === null) return
    setNavigationEnd(clampTimelineEnd(
      bars.length,
      index + Math.floor(timeline.size / 2),
      timeline.size,
    ))
  }, [bars, resolvedStudy, selectedPointId, timeline.size])

  useEffect(() => {
    if (!containerRef.current || !bars.length) return
    const container = containerRef.current
    const chart = createChart(container, {
      autoSize: true,
      height: Math.max(620, container.clientHeight),
      layout: {
        background: { type: ColorType.Solid, color: '#07111f' },
        textColor: '#aabbd0',
        panes: { separatorColor: '#263b55', separatorHoverColor: '#3f658c', enableResize: true },
      },
      grid: { vertLines: { color: '#12243a' }, horzLines: { color: '#12243a' } },
      rightPriceScale: { borderColor: '#2b425f' },
      timeScale: { borderColor: '#2b425f', timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: '#657f9f' }, horzLine: { color: '#657f9f' } },
    })
    chartRef.current = chart

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#18b987', downColor: '#ef5b67', borderVisible: false,
      wickUpColor: '#18b987', wickDownColor: '#ef5b67',
    })
    const candleData: CandlestickData<Time>[] = bars.map((bar) => ({
      time: asTime(bar.time), open: bar.open, high: bar.high, low: bar.low, close: bar.close,
    }))
    candles.setData(candleData)

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' }, priceScaleId: 'volume', priceLineVisible: false, lastValueVisible: false,
    }, 1)
    const volumeData: HistogramData<Time>[] = bars
      .filter((bar) => bar.volume !== null)
      .map((bar) => ({
        time: asTime(bar.time), value: bar.volume ?? 0,
        color: bar.close >= bar.open ? '#18b98755' : '#ef5b6755',
      }))
    volume.setData(volumeData)

    const groups = new Map(resolvedStudy.groups.map((group) => [group.id, group]))
    const paneById = new Map<string, number>([['price', 0], ['volume', 1]])
    const visiblePanels = resolvedStudy.panels.filter((panel) => panel.visible !== false)
    visiblePanels.forEach((panel, index) => {
      const paneIndex = index + 2
      paneById.set(panel.id, paneIndex)
      panel.series.forEach((definition) => {
        const common = {
          color: definition.color ?? '#59c3ff',
          lineWidth: Math.max(1, Math.min(4, Math.round(definition.line_width ?? 2))) as 1 | 2 | 3 | 4,
          priceLineVisible: false,
          lastValueVisible: true,
          title: definition.name,
        }
        if (definition.type === 'histogram') {
          const series = chart.addSeries(HistogramSeries, common, paneIndex)
          series.setData(definition.points.filter((point) => point.value !== null).map((point) => ({
            time: asTime(point.time), value: point.value as number, color: point.color ?? common.color,
          })))
        } else if (definition.type === 'area') {
          const series = chart.addSeries(AreaSeries, {
            ...common,
            lineColor: common.color,
            topColor: colorWithOpacity(common.color, 0.42),
            bottomColor: colorWithOpacity(common.color, 0.02),
          }, paneIndex)
          series.setData(definition.points.filter((point) => point.value !== null).map((point) => ({
            time: asTime(point.time), value: point.value as number,
          })))
        } else {
          const series = chart.addSeries(LineSeries, common, paneIndex)
          const points: LineData<Time>[] = definition.points.filter((point) => point.value !== null).map((point) => ({
            time: asTime(point.time), value: point.value as number,
          }))
          series.setData(points)
        }
      })
      if (panel.zero_line) {
        const zero = chart.addSeries(LineSeries, {
          color: '#70839988', lineStyle: LineStyle.Dashed, lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
        }, paneIndex)
        if (bars.length) zero.setData([{ time: asTime(bars[0].time), value: 0 }, { time: asTime(bars[bars.length - 1].time), value: 0 }])
      }
    })

    resolvedStudy.links.filter((link) => visibleGroups.has(link.group)).forEach((link) => {
      const paneIndex = paneById.get(link.pane ?? 'price') ?? 0
      const color = link.color || groups.get(link.group)?.color || '#7dd3fc'
      const series = chart.addSeries(LineSeries, {
        color, lineWidth: 2, lineStyle: link.dash === 'dash' ? LineStyle.Dashed : LineStyle.Dotted,
        priceLineVisible: false, lastValueVisible: false, title: link.label ?? '',
      }, paneIndex)
      series.setData([
        { time: asTime(link.start_time), value: link.start_value },
        { time: asTime(link.end_time), value: link.end_value },
      ])
    })

    resolvedStudy.spans.filter((span) => visibleGroups.has(span.group) && span.lower != null && span.upper != null).forEach((span) => {
      const paneIndex = paneById.get(span.pane ?? 'price') ?? 0
      const color = span.color || groups.get(span.group)?.color || '#7dd3fc'
      const series = chart.addSeries(BaselineSeries, {
        baseValue: { type: 'price', price: span.lower as number },
        topLineColor: colorWithOpacity(color, 0.8), topFillColor1: colorWithOpacity(color, span.opacity ?? 0.14),
        topFillColor2: colorWithOpacity(color, span.opacity ?? 0.14),
        bottomLineColor: colorWithOpacity(color, 0.2), bottomFillColor1: colorWithOpacity(color, 0.04),
        bottomFillColor2: colorWithOpacity(color, 0.04), priceLineVisible: false, lastValueVisible: false,
      }, paneIndex)
      series.setData([{ time: asTime(span.start_time), value: span.upper as number }, { time: asTime(span.end_time), value: span.upper as number }])
    })

    resolvedStudy.levels.filter((level) => visibleGroups.has(level.group) && (level.pane ?? 'price') === 'price').forEach((level) => {
      candles.createPriceLine({
        price: level.value, color: level.color || groups.get(level.group)?.color || '#f8c45c',
        lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: level.label ?? '',
      })
    })

    const markerPointByTime = new Map<number, StudyPoint>()
    const markers: SeriesMarker<Time>[] = []
    eventPoints.forEach((point) => {
      const time = nearestBarTime(point.time, bars)
      if (time === null) return
      markerPointByTime.set(Number(time), point)
      const selected = selectedPointId === point.id
      markers.push({
        id: point.id, time,
        position: point.role === 'exit' || point.role === 'target' ? 'aboveBar' : 'belowBar',
        shape: markerShape(point.marker, point.role),
        color: selected ? '#ffffff' : point.color || groups.get(point.group)?.color || '#7dd3fc',
        text: point.label || point.role || '', size: selected ? 2 : 1,
      })
    })
    createSeriesMarkers(candles, markers)

    chart.subscribeClick((parameter) => {
      if (!parameter.time || !onPointSelect) return
      const point = markerPointByTime.get(Number(parameter.time))
      if (point) onPointSelect(point)
    })

    const panes = chart.panes()
    if (panes[1]) panes[1].setHeight(110)
    visiblePanels.forEach((panel, index) => {
      const pane = panes[index + 2]
      if (pane) pane.setHeight(panel.height ?? 190)
    })

    chart.timeScale().setVisibleLogicalRange({
      from: (timeline.start - 0.5) as Logical,
      to: (timeline.end + 0.5) as Logical,
    })

    const observer = new ResizeObserver(() => chart.resize(container.clientWidth, container.clientHeight))
    observer.observe(container)
    return () => {
      observer.disconnect()
      if (chartRef.current === chart) chartRef.current = null
      chart.remove()
    }
  // Timeline movement is applied by the lightweight effect below; rebuilding
  // the chart for every range-input tick would make scrubbing unnecessarily expensive.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, resolvedStudy, visibleGroups, selectedPointId, eventPoints, onPointSelect])

  useEffect(() => {
    if (!chartRef.current || !timeline.size) return
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: (timeline.start - 0.5) as Logical,
      to: (timeline.end + 0.5) as Logical,
    })
  }, [timeline])

  if (!bars.length) {
    return <div className="chart-empty">Select a dataset to load its chart.</div>
  }
  const moveTimeline = (end: number) => {
    setNavigationEnd(clampTimelineEnd(bars.length, end, timeline.size))
  }
  const step = Math.max(1, Math.floor(timeline.size / 4))

  return <div className="chart-stage">
    <div className="chart-workbench" ref={containerRef} />
    <nav className="timeline-navigation" aria-label="Chart timeline navigation">
      <button type="button" onClick={() => moveTimeline(timeline.minimumEnd)} disabled={!timeline.canMoveBackward} title="Oldest loaded bars" aria-label="Jump to oldest loaded bars">|‹</button>
      <button type="button" onClick={() => moveTimeline(timeline.end - step)} disabled={!timeline.canMoveBackward} title="Move backward" aria-label="Move backward in time">‹</button>
      <div className="timeline-track">
        <div className="timeline-dates"><span>{navigationLabel(bars[timeline.start]?.time)}</span><strong>{timeline.start + 1}–{timeline.end + 1} of {bars.length.toLocaleString()} bars</strong><span>{navigationLabel(bars[timeline.end]?.time)}</span></div>
        <input
          type="range"
          min={timeline.minimumEnd}
          max={timeline.maximumEnd}
          value={timeline.end}
          step={1}
          disabled={timeline.minimumEnd === timeline.maximumEnd}
          onChange={(event) => moveTimeline(Number(event.target.value))}
          aria-label="Move chart backward or forward in time"
          aria-valuetext={`${navigationLabel(bars[timeline.start]?.time)} through ${navigationLabel(bars[timeline.end]?.time)}`}
        />
      </div>
      <button type="button" onClick={() => moveTimeline(timeline.end + step)} disabled={!timeline.canMoveForward} title="Move forward" aria-label="Move forward in time">›</button>
      <button type="button" onClick={() => moveTimeline(timeline.maximumEnd)} disabled={!timeline.canMoveForward} title="Latest loaded bars" aria-label="Jump to latest loaded bars">›|</button>
    </nav>
    <TpoProfile datasetId={datasetId} atTime={bars[timeline.end]?.time} />
  </div>
}
