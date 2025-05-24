import { useRef, useState, useEffect , useReducer} from 'react';
import './App.css';
import { ChartComponent } from './components/Chart';
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
      case 'ADD_MORE_DATA':
        const newData = [...action.payload.data, ...state.data]
        return {
          ...state,
          data: newData,
          startDate: action.payload.startDate,
          endDate: action.payload.endDate
        };
      default:
        return state;
    }
  }

  const {data, startDate, endDate} = state;
 
  const [error, setError] = useState(null);
  // Fetch data from the backend
  const fetchData = async (ticker, timeframe, startDate, endDate, type) => {
    try {
      const response = await fetch(`http://127.0.0.1:5000/stock/${ticker}/${startDate}/${endDate}?timeframe=${timeframe}`);
      const responseData = await response.json();
      if (responseData.error) {
        setError(responseData.error);
        throw new Error(responseData.error);
      }
    
      const parsedData = responseData.data
      console.log(parsedData) 
      const formattedData = parsedData.results.map((item : PolygonData) => ({
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
          data : formattedData,
          startDate, 
          endDate
        }
      }); 
    } catch (error) {
      console.error('Error fetching data:', error);
    }
  };

  const requestMore = async () => {
    const newStartDate = new Date(new Date(startDate).getTime() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const newEndDate = new Date(new Date(startDate).getTime() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    
    console.log(newStartDate, newEndDate)
    try {
      await fetchData(ticker, timeframe,newStartDate,newEndDate, 'ADD_MORE_DATA');
    } catch (error) {
      console.error('Error fetching data:', error);
      setError(error.message);
    }
  }

  // Handle search
  const handleSearch = () => {
    if (ticker) {
      fetchData(ticker, timeframe,defaultStartDate,defaultEndDate, 'RESET_AND_FETCH'); 
    } else {
      alert('Please enter a ticker symbol.');
    }
  };

  const d = [{ open: 10, high: 10.63, low: 9.49, close: 9.55, time: 1642427876 }, { open: 9.55, high: 10.30, low: 9.42, close: 9.94, time: 1642514276 }, { open: 9.94, high: 10.17, low: 9.92, close: 9.78, time: 1642600676 }, { open: 9.78, high: 10.59, low: 9.18, close: 9.51, time: 1642687076 }, { open: 9.51, high: 10.46, low: 9.10, close: 10.17, time: 1642773476 }, { open: 10.17, high: 10.96, low: 10.16, close: 10.47, time: 1642859876 }, { open: 10.47, high: 11.39, low: 10.40, close: 10.81, time: 1642946276 }, { open: 10.81, high: 11.60, low: 10.30, close: 10.75, time: 1643032676 }, { open: 10.75, high: 11.60, low: 10.49, close: 10.93, time: 1643119076 }, { open: 10.93, high: 11.53, low: 10.76, close: 10.96, time: 1643205476 }];


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
      <div className="chart-container tv-lightweight-charts" ref={chartContainerRef}>
        {/* <ChartComponent data={data} requestMore={requestMore} /> */}
        <CustomChart candlestickData={d} theme={"dark"}/>
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