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
  candlestickData?: Array<LightweightCharts.CandlestickData<Time>>
  initialSymbol?: string
  theme?: "light" | "dark"
  autosize?: boolean
  timeVisible?: boolean
  onCrosshairMove?: (param: any) => void
  customIndicators?: Array<{
    name: string
    data: LineData[]
    options?: CustomPlotOptions
  }>
}

export function CustomChart({
  width = "90vw",
  height = 500,
  candlestickData = [],
  initialSymbol = "Custom Backtest",
  theme = "light",
  autosize = true,
  timeVisible = true,
  onCrosshairMove,
  customIndicators = [],
}: CustomChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const [chartCreated, setChartCreated] = useState(false)

  // Chart instance and series references
  const chartRef = useRef<any>(null)
  const candlestickSeriesRef = useRef<any>(null)
  const customSeriesRefs = useRef<any[]>([])

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
    console.log(chart)
    // Create candlestick series
    const candlestickSeries = chart.addSeries(LightweightCharts.CandlestickSeries,{
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    })
    candlestickSeries.setData(candlestickData)

    chart.timeScale().fitContent();

    // Store references
    chartRef.current = chart
    console.log(candlestickSeries)
   // candlestickSeriesRef.current = candlestickSeries

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

    setChartCreated(true)

    return () => {
      chart.remove()
    }
  }, [width, height, theme, autosize, timeVisible, candlestickData.length])

  

  //Add custom indicators when chart is created and when they change
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

  // Update candlestick data when it changes
  useEffect(() => {
    if (candlestickSeriesRef.current && candlestickData.length > 0) {
      candlestickSeriesRef.current.setData(candlestickData)
    }
  }, [candlestickData])

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
    <div className="w-full h-full">
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
