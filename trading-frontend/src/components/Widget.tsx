"use client"

import { useEffect, useRef } from "react"

declare global {
  interface Window {
    TradingView: any
  }
}

interface TradingViewWidgetProps {
  symbol?: string
  theme?: "light" | "dark"
  width?: string | number
  height?: string | number
  interval?: string
  timezone?: string
  style?: "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9"
  locale?: string
  toolbar_bg?: string
  enable_publishing?: boolean
  allow_symbol_change?: boolean
  container_id?: string
  hide_top_toolbar?: boolean
  hide_legend?: boolean
  save_image?: boolean
  studies?: string[]
  show_popup_button?: boolean
  popup_width?: string | number
  popup_height?: string | number
  autosize?: boolean
  hide_side_toolbar?: boolean
  details?: boolean
  hotlist?: boolean
  calendar?: boolean
  news?: string[]
  studies_overrides?: object
  overrides?: object
  enabled_features?: string[]
  disabled_features?: string[]
  withdateranges?: boolean
}

export function TradingViewWidget({
  symbol = "NASDAQ:AAPL",
  theme = "light",
  width = "100%",
  height = 500,
  interval = "D",
  timezone = "Etc/UTC",
  style = "1",
  locale = "en",
  toolbar_bg = "#f1f3f6",
  enable_publishing = false,
  allow_symbol_change = true,
  container_id = "tradingview_widget",
  hide_top_toolbar = false,
  hide_legend = false,
  save_image = true,
  studies = [],
  show_popup_button = false,
  popup_width = "1000",
  popup_height = "650",
  autosize = false,
  hide_side_toolbar = false,
  details = false,
  hotlist = false,
  calendar = false,
  news = [],
  studies_overrides = {},
  overrides = {},
  enabled_features = [],
  disabled_features = [],
  withdateranges = false,
}: TradingViewWidgetProps) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Remove any existing script to avoid duplicates
    const existingScript = document.getElementById("tradingview-widget-script")
    if (existingScript) {
      existingScript.remove()
    }

    // Create script element
    const script = document.createElement("script")
    script.id = "tradingview-widget-script"
    script.src = "https://s3.tradingview.com/tv.js"
    script.async = true
    script.onload = () => {
      if (window.TradingView && container.current) {
        new window.TradingView.widget({
          width: width,
          height: height,
          symbol: symbol,
          interval: interval,
          timezone: timezone,
          theme: theme,
          style: style,
          locale: locale,
          toolbar_bg: toolbar_bg,
          enable_publishing: enable_publishing,
          allow_symbol_change: allow_symbol_change,
          container_id: container_id,
          hide_top_toolbar: hide_top_toolbar,
          hide_legend: hide_legend,
          save_image: save_image,
          studies: studies,
          show_popup_button: show_popup_button,
          popup_width: popup_width,
          popup_height: popup_height,
          autosize: autosize,
          hide_side_toolbar: hide_side_toolbar,
          details: details,
          hotlist: hotlist,
          calendar: calendar,
          news: news,
          studies_overrides: studies_overrides,
          overrides: overrides,
          enabled_features: enabled_features,
          disabled_features: disabled_features,
          withdateranges: withdateranges,
        })
      }
    }
    document.head.appendChild(script)

    return () => {
      if (existingScript && document.head.contains(existingScript)) {
        document.head.removeChild(existingScript)
      }
    }
  }, [
    symbol,
    theme,
    width,
    height,
    interval,
    timezone,
    style,
    locale,
    toolbar_bg,
    enable_publishing,
    allow_symbol_change,
    container_id,
    hide_top_toolbar,
    hide_legend,
    save_image,
    studies,
    show_popup_button,
    popup_width,
    popup_height,
    autosize,
    hide_side_toolbar,
    details,
    hotlist,
    calendar,
    news,
    studies_overrides,
    overrides,
    enabled_features,
    disabled_features,
    withdateranges,
  ])

  return (
    <div className="w-full">
      <div id={container_id} ref={container} />
    </div>
  )
}
