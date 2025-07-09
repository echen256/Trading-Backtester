import { useRef, useState, useEffect, useReducer, useCallback } from 'react';
import './App.css';
import { CustomChart } from './components/CustomChart';


interface PolygonData {
  t: number; // timestamp 
  o: number; // open
  h: number; // high
  l: number; // low
  c: number; // close
  v: number; // volume
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


  const [state, dispatch] = useReducer(reducer, {
    data: [],
    startDate: defaultStartDate,
    endDate: defaultEndDate,
  });

  function reducer(state, action) {
    switch (action.type) {
      case 'RESET_AND_FETCH':
        return {
          ...state,
          data: action.payload.data,
          startDate: action.payload.startDate,
          endDate: action.payload.endDate
        };
      case 'ADD_MORE_DATA': {
        const newData = [...action.payload.data, ...state.data]
        return {
          ...state,
          data: newData,
          startDate: action.payload.startDate,
          endDate: action.payload.endDate
        };
      }
      default:
        return state;
    }
  }

  const { data, startDate } = state;

  const [error, setError] = useState(null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Fetch data from the backend
  const fetchData = useCallback(async (ticker, timeframe, startDate, endDate, type) => {
    try {
      const response = await fetch(`http://127.0.0.1:5000/stock/${ticker}/${startDate}/${endDate}?timeframe=${timeframe}`);
      const responseData = await response.json();
      if (responseData.error) {
        setError(responseData.error);
        throw new Error(responseData.error);
      }

      const parsedData = responseData.data
      console.log(parsedData, startDate, endDate)
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
          startDate,
          endDate
        }
      });
    } catch (error) {
      console.error('Error fetching data:', error);
    }
  }, []);

  const requestMore = useCallback(async () => {
    if (isLoadingMore) return; // Prevent multiple simultaneous requests

    setIsLoadingMore(true);
    const newStartDate = new Date(new Date(startDate).getTime() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const newEndDate = new Date(new Date(startDate).getTime() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];

    console.log('Loading more data:', newStartDate, 'to', newEndDate);
    try {
      await fetchData(ticker, timeframe, newStartDate, newEndDate, 'ADD_MORE_DATA');
    } catch (error) {
      console.error('Error fetching data:', error);
      setError(error.message);
    } finally {
      setIsLoadingMore(false);
    }
  }, [startDate, ticker, timeframe, isLoadingMore, fetchData]);

  // Handle search
  const handleSearch = () => {
    if (ticker) {
      fetchData(ticker, timeframe, defaultStartDate, defaultEndDate, 'RESET_AND_FETCH');
    } else {
      alert('Please enter a ticker symbol.');
    }
  };

  // Fetch initial data on mount
  useEffect(() => {
    if (ticker) {
      fetchData(ticker, timeframe, defaultStartDate, defaultEndDate, 'RESET_AND_FETCH');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps


  return (
    <div className="app">
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
      <div className="chart-container tv-lightweight-charts" ref={chartContainerRef}>
        <CustomChart candlestickData={data} theme={"dark"} requestMore={requestMore} />
      </div>
      <ErrorAlert error={error} />
    </div>
  );
}

const ErrorAlert = (props) => {

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