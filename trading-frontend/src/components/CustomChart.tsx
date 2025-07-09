"use client"

import { useEffect, useRef, useState } from "react"
import * as LightweightCharts from "lightweight-charts"
import { Time } from "lightweight-charts"

export interface CandlestickData {
  time: string | number
  open: number
  high: number
  close: number
  low: number
  volume?: number
}

export interface LineData {
  time: string | number
  value: number
}

export interface CustomPlotOptions {
  color?: string
  lineWidth?: number
  lineStyle?: number
  lineType?: "line" | "histogram" | "area"
  priceScaleId?: string
  priceFormat?: {
    type?: string
    precision?: number
    minMove?: number
  }
}

interface CustomChartProps {
  width?: number | string
  height?: number | string
  initialData?: Array<LightweightCharts.CandlestickData<Time>>
  incrementalData?: Array<LightweightCharts.CandlestickData<Time>>
  currentTicker?: string
  theme?: "light" | "dark"
  autosize?: boolean
  timeVisible?: boolean
  onCrosshairMove?: (param: any) => void
  requestMore?: () => void
  customIndicators?: Array<{
    name: string
    data: LineData[]
    options?: CustomPlotOptions
  }>
}

export function CustomChart({
  width = "90vw",
  height = 500,
  initialData = [],
  incrementalData = [],
  currentTicker = "UNKNOWN",
  theme = "light",
  autosize = true,
  timeVisible = true,
  onCrosshairMove,
  requestMore,
  customIndicators = [],
}: CustomChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const [chartCreated, setChartCreated] = useState(false)
  const [visibleRange, setVisibleRange] = useState<{ from: number; to: number } | null>(null)
  const [visualRangeLoading, setVisualRangeLoading] = useState(false)
  // Chart instance and series references
  const chartRef = useRef<any>(null)
  const candlestickSeriesRef = useRef<any>(null)
  const customSeriesRefs = useRef<any[]>([])
  const loadingRef = useRef(false)
  const [internalTicker, setInternalTicker] = useState<string>('')
  const [internalDataCount, setInternalDataCount] = useState<number>(0)
  const [updateError, setUpdateError] = useState<string | null>(null)

  useEffect(() => {
    if (!chartContainerRef.current) return

    // Set up chart
    const chart = LightweightCharts.createChart(chartContainerRef.current, {
      width: typeof width === "number" ? width : chartContainerRef.current.clientWidth,
      height: typeof height === "number" ? height : Number(height),
      layout: {
        background: { type: LightweightCharts.ColorType.Solid, color: theme === "light" ? "#ffffff" : "#131722" },
        textColor: theme === "light" ? "#191919" : "#D9D9D9",
      },
      grid: {
        vertLines: { color: theme === "light" ? "#E6E6E6" : "#1f2937" },
        horzLines: { color: theme === "light" ? "#E6E6E6" : "#1f2937" },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
      },
      timeScale: {
        timeVisible: timeVisible,
        borderColor: theme === "light" ? "#D6DCDE" : "#363c4e",
      },
      rightPriceScale: {
        borderColor: theme === "light" ? "#D6DCDE" : "#363c4e",
      },
      handleScroll: {
        vertTouchDrag: false,
      },
    })
    // Create candlestick series 
    const candlestickSeries = chart.addSeries(LightweightCharts.CandlestickSeries,{
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    }) 
    // Store references
    chartRef.current = chart
    candlestickSeriesRef.current = candlestickSeries
 
    setChartCreated(true)
    const handleVisibleLogicalRangeChange = async () => {
      const currentRange = chart.timeScale().getVisibleLogicalRange()
      if (currentRange?.from && currentRange?.to && currentRange?.from < 30 && !loadingRef.current) {
        loadingRef.current = true
        setVisualRangeLoading(true)
        
        // Call requestMore if provided
        if (requestMore) {
          await requestMore()
        }
        
        // Reset loading state after a delay
        setTimeout(() => {
          loadingRef.current = false
          setVisualRangeLoading(false)
        }, 1000)
      }
    }
  
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange)

    // Handle resize
    if (autosize) {
      const resizeObserver = new ResizeObserver((entries) => {
        if (entries.length === 0 || !entries[0].contentRect) return
        const { width: newWidth, height: newHeight } = entries[0].contentRect
        chart.applyOptions({ width: newWidth, height: newHeight })
      })

      resizeObserver.observe(chartContainerRef.current)

      return () => {
        resizeObserver.disconnect()
        chart.remove()
      }
    }
 
  
    return () => {
      chart.remove()
    }
  }, [width, height, theme, autosize, timeVisible])

  
  useEffect(() => {
    if (!chartCreated || !chartRef.current) return
  
    // Clear previous custom series
    customSeriesRefs.current.forEach((series) => {
      if (series && chartRef.current) {
        chartRef.current.removeSeries(series)
      }
    })
    customSeriesRefs.current = []
  
    // Add new custom series
    customIndicators.forEach((indicator) => {
      let series
  
      switch (indicator.options?.lineType) {
        case "histogram":
          series = chartRef.current.addHistogramSeries({
            color: indicator.options?.color || "#2962FF",
            lineWidth: indicator.options?.lineWidth || 2,
            priceScaleId: indicator.options?.priceScaleId,
            priceFormat: indicator.options?.priceFormat,
          })
          break
        case "area":
          series = chartRef.current.addAreaSeries({
            topColor: indicator.options?.color || "#2962FF",
            bottomColor: indicator.options?.color ? `${indicator.options.color}00` : "#2962FF00",
            lineColor: indicator.options?.color || "#2962FF",
            lineWidth: indicator.options?.lineWidth || 2,
            priceScaleId: indicator.options?.priceScaleId,
            priceFormat: indicator.options?.priceFormat,
          })
          break
        case "line":
        default:
          series = chartRef.current.addLineSeries({
            color: indicator.options?.color || "#2962FF",
            lineWidth: indicator.options?.lineWidth || 2,
            lineStyle: indicator.options?.lineStyle || 0,
            priceScaleId: indicator.options?.priceScaleId,
            priceFormat: indicator.options?.priceFormat,
          })
      }
  
      if (series) {
        series.setData(indicator.data)
        customSeriesRefs.current.push(series)
      }
    })
  }, [chartCreated, customIndicators])
  
  // Handle initial data load (when ticker changes or first load)
  useEffect(() => {
    if (!candlestickSeriesRef.current || !initialData.length) return
    
    // Check if ticker changed - if so, reset everything
    if (currentTicker !== internalTicker) {
      console.log(`Ticker changed from ${internalTicker} to ${currentTicker} - resetting chart data`)
      setInternalTicker(currentTicker)
      setInternalDataCount(0)
      setUpdateError(null)
      
      // Use setData for initial load
      candlestickSeriesRef.current.setData(initialData)
      setInternalDataCount(initialData.length)
      
      // Fit content for new ticker
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent()
      }
    } else if (initialData.length > 0 && internalDataCount === 0) {
      // First time loading data for this ticker
      console.log(`Setting initial data for ${currentTicker}: ${initialData.length} bars`)
      candlestickSeriesRef.current.setData(initialData)
      setInternalDataCount(initialData.length)
      
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent()
      }
    }
  }, [initialData, currentTicker, internalTicker, internalDataCount])
  
  // Handle incremental data updates
  useEffect(() => {
    if (!candlestickSeriesRef.current || !incrementalData.length || currentTicker !== internalTicker) return
    

    try {
      const data = candlestickSeriesRef.current.data()
      candlestickSeriesRef.current.setData( [...incrementalData,...data]) 
      setInternalDataCount(prev => prev + incrementalData.length)
    } catch (error) {
      const errorMsg = `Failed to update chart data: ${error.message}`
      console.error(errorMsg, error)
      setUpdateError(errorMsg)
    }
  }, [incrementalData, currentTicker])


  // Set up crosshair move handler
  useEffect(() => {
    if (!chartRef.current || !onCrosshairMove) return

    chartRef.current.subscribeCrosshairMove(onCrosshairMove)

    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeCrosshairMove(onCrosshairMove)
      }
    }
  }, [onCrosshairMove, chartCreated])


 
  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* Bar count warning */}
      {internalDataCount > 10000 && (
        <div style={{
          position: 'absolute',
          top: '40px',
          left: '8px',
          zIndex: 10,
          backgroundColor: '#ff9800',
          color: 'white',
          padding: '8px 12px',
          borderRadius: '4px',
          fontSize: '14px',
          fontWeight: 'bold'
        }}>
          ⚠️ {internalDataCount.toLocaleString()} bars loaded - Performance may be impacted
        </div>
      )}
      
      {/* Update error notification */}
      {updateError && (
        <div style={{
          position: 'absolute',
          top: internalDataCount > 10000 ? '80px' : '40px',
          left: '8px',
          zIndex: 10,
          backgroundColor: '#f44336',
          color: 'white',
          padding: '8px 12px',
          borderRadius: '4px',
          fontSize: '14px',
          cursor: 'pointer'
        }}
        onClick={() => setUpdateError(null)}
        title="Click to dismiss"
        >
          ❌ {updateError}
        </div>
      )}
      
      <div
        ref={chartContainerRef}
        style={{
          width: typeof width === "string" ? width : `${width}px`,
          height: typeof height === "string" ? height : `${height}px`,
        }}
      />
    </div>
  )
}

// Helper function to add a custom plot to the chart
export function addCustomPlot(
  indicators: Array<{
    name: string
    data: LineData[]
    options?: CustomPlotOptions
  }>,
  name: string,
  data: LineData[],
  options?: CustomPlotOptions,
) {
  // Create a new array to avoid mutating the original
  const newIndicators = [...indicators]

  // Check if indicator with this name already exists
  const existingIndex = newIndicators.findIndex((ind) => ind.name === name)

  if (existingIndex >= 0) {
    // Update existing indicator
    newIndicators[existingIndex] = {
      ...newIndicators[existingIndex],
      data,
      options: options || newIndicators[existingIndex].options,
    }
  } else {
    // Add new indicator
    newIndicators.push({
      name,
      data,
      options,
    })
  }

  return newIndicators
}
