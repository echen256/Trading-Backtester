import { useRef, useState, useEffect, useReducer, useCallback } from 'react';
import './App.css';
import { CustomChart } from './components/CustomChart';
import { Watchlist } from './components/Watchlist';


interface PolygonData {
  t: number; // timestamp 
  o: number; // open
  h: number; // high
  l: number; // low
  c: number; // close
  v: number; // volume
}

interface AppState {
  data: any[];
  initialData?: any[];
  incrementalData?: any[];
  currentTicker?: string;
  startDate: string;
  endDate: string;
}

interface AppAction {
  type: string;
  payload: {
    data: any[];
    ticker?: string;
    startDate?: string;
    endDate?: string;
  };
}

const BAR_LOOKBACK = 100;
const defaultTicker = 'QQQ';
const defaultTimeframe = '1d';

function App() {
  const defaultEndDate = new Date().toISOString().split('T')[0];
  const defaultStartDate = new Date(Date.now() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  const chartContainerRef = useRef(null);
  const [ticker, setTicker] = useState(defaultTicker);
  const [timeframe, setTimeframe] = useState(defaultTimeframe); // Default timeframe


  const [loading , setLoading] = useState(false)
  const [backtestInput, setBacktestInput] = useState('');
  const resetChartRef = useRef<() => void>(() => {});

  const [state, dispatch] = useReducer(reducer, {
    data: [],
    startDate: defaultStartDate,
    endDate: defaultEndDate,
  });

  function reducer(state: AppState, action: AppAction): AppState {
    switch (action.type) {
      case 'SET_INITIAL_DATA':
        return {
          ...state,
          initialData: action.payload.data,
          incrementalData: [], // Reset incremental data
          currentTicker: action.payload.ticker || '',
          startDate: action.payload.startDate || state.startDate,
          endDate: action.payload.endDate || state.endDate
        };
      case 'ADD_INCREMENTAL_DATA': {
        return {
          ...state,
          incrementalData: action.payload.data,
          startDate: action.payload.startDate || state.startDate, // This should be the NEW earlier startDate
          // Don't update endDate for incremental data - keep the original end
        };
      }
      default:
        return state;
    }
  }

  const {initialData, incrementalData, currentTicker} = state;
  

  
  const [error, setError] = useState<string | null>(null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  useEffect(() => {
    if (loading) {
      requestMore()
      setLoading(false)
    }
  }, [loading])

  // Fetch data from the backend
  const fetchData = useCallback(async (ticker: string, timeframe: string, startDate: string, endDate: string, type: string) => {
    try {
      const response = await fetch(`http://127.0.0.1:5000/stock/${ticker}/${startDate}/${endDate}?timeframe=${timeframe}`);
      const responseData = await response.json();
      if (responseData.error) {
        setError(responseData.error);
        throw new Error(responseData.error);
      }

      const parsedData = responseData.data
      const formattedData = parsedData.results.map((item: PolygonData) => ({
        time: new Date(item.t / 1000).getTime(),
        open: item.o,
        high: item.h,
        low: item.l,
        close: item.c,
        volume: item.v,
      }));

      dispatch({
        type,
        payload: {
          data: formattedData,
          ticker: ticker, // Pass ticker to the payload
          startDate,
          endDate
        }
      });
    } catch (error) {
      console.error('Error fetching data:', error);
    }
  }, []);

  const requestMore = useCallback(async () => {
    if (isLoadingMore) return; 
    
    
    const currentStartDate = state.startDate 
    const newStartDate = new Date(new Date(currentStartDate).getTime() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const newEndDate = new Date(new Date(currentStartDate).getTime() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  
    try {
      await fetchData(ticker, timeframe, newStartDate, newEndDate, 'ADD_INCREMENTAL_DATA');
    } catch (error) {
      console.error('Error fetching data:', error);
      setError(error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setIsLoadingMore(false);
    }
  }, [state.startDate, ticker, timeframe, isLoadingMore]);

  // Handle search
  const handleSearch = () => {
    if (ticker) {
      fetchData(ticker, timeframe, defaultStartDate, defaultEndDate, 'SET_INITIAL_DATA');
    } else {
      alert('Please enter a ticker symbol.');
    }
  };

  // Handle watchlist ticker selection
  const handleWatchlistTickerSelect = (selectedTicker: string) => {
    setTicker(selectedTicker);
    fetchData(selectedTicker, timeframe, defaultStartDate, defaultEndDate, 'SET_INITIAL_DATA');
  };

  // Handle backtest form submission
  const handleBacktestSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // TODO: Implement backtest functionality
  };

  // Fetch initial data on mount
  useEffect(() => {
    if (ticker) {
      fetchData(ticker, timeframe, defaultStartDate, defaultEndDate, 'SET_INITIAL_DATA');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps


  return (
    <div className="app">
      <div className="main-layout">
        <div className="left-panel">
          <Watchlist 
            onTickerSelect={handleWatchlistTickerSelect}
            currentTicker={ticker}
          />
          <div className="controls-container">
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              className="timeframe-select"
            >
              <option value="1m">1 Minute</option>
              <option value="5m">5 Minutes</option>
              <option value="15m">15 Minutes</option>
              <option value="1h">1 Hour</option>
              <option value="1d">1 Day</option>
              <option value="1wk">1 Week</option>
            </select>
            <input
              type="text"
              defaultValue={ticker}
              onBlur={(e) => setTicker(e.target.value)}
              placeholder="Enter ticker (e.g., QQQ)"
              className="ticker-input"
            />
            <button onClick={handleSearch} className="search-button">
              Search
            </button>
          </div>
          <div className="status-bar">
            {isLoadingMore && (
              <div className="loading-indicator">
                Loading more data...
              </div>
            )}
          </div>
        </div>
        
        <div className="right-panel">
          <div className="chart-container tv-lightweight-charts" ref={chartContainerRef}>
            <CustomChart 
              initialData={initialData}
              incrementalData={incrementalData}
              currentTicker={currentTicker}
              theme={"dark"} 
              requestMore={() => setLoading(true)}
              onResetChart={resetChartRef}
            />
          </div>
          
          <div className="bottom-controls">
            <button 
              onClick={() => resetChartRef.current?.()}
              className="reset-chart-btn"
            >
              Reset Chart View
            </button>
            
            <form onSubmit={handleBacktestSubmit} className="backtest-form">
              <input
                type="text"
                value={backtestInput}
                onChange={(e) => setBacktestInput(e.target.value)}
                placeholder="Enter backtest parameters"
                className="backtest-input"
              />
              <button type="submit" className="backtest-submit-btn">
                RUN BACKTEST
              </button>
            </form>
          </div>
        </div>
      </div>
      <ErrorAlert error={error} />
    </div>
  );
}

const ErrorAlert = (props: { error: string | null }) => {

  return (
    <div>
      {
        props.error &&
        <div className="error-alert">
          <p>{props.error}</p>
        </div>
      }
    </div>

  )
}

export default App;