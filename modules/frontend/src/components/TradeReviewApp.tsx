import { useEffect, useMemo, useState } from 'react';
import { CustomChart } from './CustomChart';
import './TradeReviewApp.css';

interface ReviewTrade {
  id: number;
  contract_symbol: string;
  contract_label: string;
  underlying_symbol: string;
  quantity: number;
  direction: string;
  pnl: number;
  open_date: string;
  close_date: string;
  open_price: number;
  close_price: number;
  chart_start: string;
  chart_end: string;
}

interface ReviewDay {
  date: string;
  trade_count: number;
  net_pnl: number;
  trades: ReviewTrade[];
}

interface ReviewPayload {
  source_csv: string;
  generated_at: string;
  days: ReviewDay[];
}

interface PolygonBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

const DEFAULT_DATA_PATH = '/trade-review-data.json';
const BACKEND_BASE_URL = 'http://127.0.0.1:5000';

function currency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    signDisplay: 'always',
  }).format(value);
}

function dataPathFromLocation(): string {
  const params = new URLSearchParams(window.location.search);
  const value = params.get('data');
  if (!value) {
    return DEFAULT_DATA_PATH;
  }
  return value.startsWith('/') ? value : `/${value}`;
}

export function TradeReviewApp() {
  const [payload, setPayload] = useState<ReviewPayload | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [selectedDayIndex, setSelectedDayIndex] = useState(0);
  const [selectedTradeIndex, setSelectedTradeIndex] = useState(0);
  const [chartData, setChartData] = useState<any[]>([]);
  const [chartError, setChartError] = useState<string | null>(null);
  const [chartLoading, setChartLoading] = useState(false);

  const dataPath = useMemo(() => dataPathFromLocation(), []);
  const selectedDay = payload?.days[selectedDayIndex] ?? null;
  const selectedTrade = selectedDay?.trades[selectedTradeIndex] ?? null;

  useEffect(() => {
    let cancelled = false;
    async function loadReviewData() {
      try {
        setDataError(null);
        const response = await fetch(dataPath);
        if (!response.ok) {
          throw new Error(`Failed to load review data from ${dataPath} (${response.status})`);
        }
        const body = (await response.json()) as ReviewPayload;
        if (!cancelled) {
          setPayload(body);
          setSelectedDayIndex(0);
          setSelectedTradeIndex(0);
        }
      } catch (error) {
        if (!cancelled) {
          setDataError(error instanceof Error ? error.message : 'Failed to load review data.');
        }
      }
    }

    loadReviewData();
    return () => {
      cancelled = true;
    };
  }, [dataPath]);

  useEffect(() => {
    if (!selectedDay) {
      return;
    }
    if (selectedTradeIndex >= selectedDay.trades.length) {
      setSelectedTradeIndex(0);
    }
  }, [selectedDay, selectedTradeIndex]);

  useEffect(() => {
    if (!selectedTrade) {
      setChartData([]);
      return;
    }

    const trade = selectedTrade;
    let cancelled = false;
    async function loadChart() {
      try {
        setChartLoading(true);
        setChartError(null);
        const url =
          `${BACKEND_BASE_URL}/stock/${trade.underlying_symbol}` +
          `/${trade.chart_start}/${trade.chart_end}?timeframe=1d`;
        const response = await fetch(url);
        const responseData = await response.json();
        if (!response.ok || responseData.error) {
          throw new Error(responseData.error || `Failed to load market data (${response.status})`);
        }
        const formattedData = (responseData.data.results as PolygonBar[]).map((item) => ({
          time: new Date(item.t).toISOString().slice(0, 10),
          open: item.o,
          high: item.h,
          low: item.l,
          close: item.c,
          volume: item.v,
        }));
        if (!cancelled) {
          setChartData(formattedData);
        }
      } catch (error) {
        if (!cancelled) {
          setChartData([]);
          setChartError(error instanceof Error ? error.message : 'Failed to load chart data.');
        }
      } finally {
        if (!cancelled) {
          setChartLoading(false);
        }
      }
    }

    loadChart();
    return () => {
      cancelled = true;
    };
  }, [selectedTrade]);

  const tradeMarkers = selectedTrade
    ? [
        {
          id: `entry-${selectedTrade.id}`,
          time: selectedTrade.open_date,
          position: 'belowBar' as const,
          shape: 'arrowUp' as const,
          color: '#2ecc71',
          text: `Entry ${selectedTrade.open_date}`,
        },
        {
          id: `exit-${selectedTrade.id}`,
          time: selectedTrade.close_date,
          position: 'aboveBar' as const,
          shape: 'arrowDown' as const,
          color: '#e74c3c',
          text: `Exit ${selectedTrade.close_date}`,
        },
      ]
    : [];

  function moveDay(offset: number): void {
    if (!payload?.days.length) return;
    const nextDayIndex = (selectedDayIndex + offset + payload.days.length) % payload.days.length;
    setSelectedDayIndex(nextDayIndex);
    setSelectedTradeIndex(0);
  }

  function moveTrade(offset: number): void {
    if (!selectedDay?.trades.length) return;
    const nextTradeIndex = (selectedTradeIndex + offset + selectedDay.trades.length) % selectedDay.trades.length;
    setSelectedTradeIndex(nextTradeIndex);
  }

  return (
    <div className="trade-review-app">
      <aside className="trade-review-sidebar">
        <div className="trade-review-panel">
          <h1>Trade Review</h1>
          <p className="trade-review-meta">
            Review data: <code>{dataPath}</code>
          </p>
          {payload && (
            <p className="trade-review-meta">
              Source: <code>{payload.source_csv}</code>
            </p>
          )}
          {dataError && (
            <div className="trade-review-error">
              <p>{dataError}</p>
              <p>
                Export review data into <code>modules/frontend/public/trade-review-data.json</code> and reload.
              </p>
            </div>
          )}
        </div>

        <div className="trade-review-panel">
          <div className="trade-review-toolbar">
            <button onClick={() => moveDay(-1)} disabled={!payload?.days.length}>Previous Day</button>
            <button onClick={() => moveDay(1)} disabled={!payload?.days.length}>Next Day</button>
          </div>
          <div className="trade-review-day-list">
            {payload?.days.map((day, index) => (
              <button
                key={day.date}
                className={`trade-review-day-item ${index === selectedDayIndex ? 'active' : ''}`}
                onClick={() => {
                  setSelectedDayIndex(index);
                  setSelectedTradeIndex(0);
                }}
              >
                <span>{day.date}</span>
                <span>{day.trade_count} trades</span>
                <strong>{currency(day.net_pnl)}</strong>
              </button>
            ))}
          </div>
        </div>

        <div className="trade-review-panel">
          <div className="trade-review-toolbar">
            <button onClick={() => moveTrade(-1)} disabled={!selectedDay?.trades.length}>Previous Trade</button>
            <button onClick={() => moveTrade(1)} disabled={!selectedDay?.trades.length}>Next Trade</button>
          </div>
          <div className="trade-review-trade-list">
            {selectedDay?.trades.map((trade, index) => (
              <button
                key={trade.id}
                className={`trade-review-trade-item ${index === selectedTradeIndex ? 'active' : ''}`}
                onClick={() => setSelectedTradeIndex(index)}
              >
                <span>{trade.contract_label}</span>
                <span>{trade.direction} x {trade.quantity}</span>
                <strong>{currency(trade.pnl)}</strong>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <main className="trade-review-main">
        <div className="trade-review-header trade-review-panel">
          {selectedTrade ? (
            <>
              <div>
                <h2>{selectedTrade.contract_label}</h2>
                <p className="trade-review-meta">
                  Underlying <code>{selectedTrade.underlying_symbol}</code> | Entry {selectedTrade.open_date} | Exit {selectedTrade.close_date}
                </p>
              </div>
              <div className="trade-review-stats">
                <div>
                  <span>PnL</span>
                  <strong>{currency(selectedTrade.pnl)}</strong>
                </div>
                <div>
                  <span>Open</span>
                  <strong>{selectedTrade.open_price.toFixed(2)}</strong>
                </div>
                <div>
                  <span>Close</span>
                  <strong>{selectedTrade.close_price.toFixed(2)}</strong>
                </div>
              </div>
            </>
          ) : (
            <h2>No trade selected</h2>
          )}
        </div>

        <div className="trade-review-chart trade-review-panel">
          {chartLoading && <p className="trade-review-meta">Loading chart...</p>}
          {chartError && <p className="trade-review-error-inline">{chartError}</p>}
          <CustomChart
            height={640}
            initialData={chartData}
            currentTicker={selectedTrade?.underlying_symbol ?? 'REVIEW'}
            theme="dark"
            tradeMarkers={tradeMarkers}
          />
        </div>
      </main>
    </div>
  );
}
