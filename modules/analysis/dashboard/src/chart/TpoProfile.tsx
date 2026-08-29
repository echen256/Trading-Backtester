import { useEffect, useMemo, useState } from 'react'

import { getTpoProfile } from '../api'
import type { TpoProfileResponse } from '../types'

interface TpoProfileProps {
  datasetId: string
  atTime?: string
}

function price(value: number, bracketSize: number): string {
  const digits = bracketSize < 0.01 ? 4 : bracketSize < 0.1 ? 3 : bracketSize < 1 ? 2 : 1
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function clock(value: string, timezone: string): string {
  return new Date(value).toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit', timeZone: timezone,
    timeZoneName: 'short',
  })
}

export function TpoProfile({ datasetId, atTime }: TpoProfileProps) {
  const [profile, setProfile] = useState<TpoProfileResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!datasetId || !atTime) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError(null)
      getTpoProfile(datasetId, atTime, controller.signal)
        .then(setProfile)
        .catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === 'AbortError') return
          setError(reason instanceof Error ? reason.message : String(reason))
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }, 120)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [atTime, datasetId])

  const maximumCount = useMemo(
    () => profile?.available ? Math.max(...profile.levels.map((level) => level.count), 1) : 1,
    [profile],
  )

  if (error) {
    return <section className="tpo-panel tpo-unavailable"><div><strong>TPO profile unavailable</strong><p>{error}</p></div></section>
  }
  if (!profile) {
    return <section className="tpo-panel tpo-unavailable"><div><strong>Building TPO profile…</strong><p>Anchored to the slider's right edge.</p></div></section>
  }
  if (!profile.available) {
    return <section className="tpo-panel tpo-unavailable"><div><strong>{profile.symbol} TPO unavailable</strong><p>{profile.reason}</p></div></section>
  }

  return <section className={`tpo-panel ${loading ? 'is-loading' : ''}`}>
    <header className="tpo-header">
      <div>
        <span className="tpo-kicker">Dynamic market profile</span>
        <h3>{profile.symbol} · {profile.session_date}</h3>
        <p>{profile.session_label} · {profile.period_minutes}-minute TPO periods · through {clock(profile.profile_through, profile.session_timezone)}</p>
      </div>
      <div className="tpo-status"><span className={profile.complete ? 'complete' : 'developing'}>{profile.complete ? 'Complete session' : 'Developing session'}</span><small>{profile.bar_count.toLocaleString()} native bars · {profile.total_tpos.toLocaleString()} TPOs</small></div>
    </header>
    <div className="tpo-metrics">
      <div><span>POC</span><strong>{price(profile.poc, profile.bracket_size)}</strong></div>
      <div><span>Value area</span><strong>{price(profile.val, profile.bracket_size)}–{price(profile.vah, profile.bracket_size)}</strong></div>
      <div><span>Initial balance</span><strong>{price(profile.ib_low, profile.bracket_size)}–{price(profile.ib_high, profile.bracket_size)}</strong></div>
      <div><span>Session range</span><strong>{price(profile.session_low, profile.bracket_size)}–{price(profile.session_high, profile.bracket_size)}</strong></div>
    </div>
    <div className="tpo-profile" role="img" aria-label={`${profile.symbol} TPO distribution for ${profile.session_date}`}>
      {profile.levels.map((level) => <div className={`tpo-level ${level.in_value_area ? 'value-area' : ''} ${level.is_poc ? 'poc' : ''}`} key={level.price}>
        <span className="tpo-price">{price(level.price, profile.bracket_size)}</span>
        <div className="tpo-bar-track">
          <div className="tpo-bar" style={{ width: `${Math.max(3, level.count / maximumCount * 100)}%` }}>
            <span>{level.letters.join(' ')}</span>
          </div>
        </div>
        <span className="tpo-count">{level.count}</span>
      </div>)}
    </div>
    <footer className="tpo-legend"><span><i className="outside" /> Outside value</span><span><i className="value" /> 70% value area</span><span><i className="poc" /> Point of control</span><small>Profile follows the chart slider and uses native bars without future-session data.</small></footer>
  </section>
}
