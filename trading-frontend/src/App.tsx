import { useRef, useState, useEffect } from 'react';
import './App.css';
import { ChartComponent } from './components/Chart';

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
  const chartContainerRef = useRef(null);
  const [ticker, setTicker] = useState(defaultTicker);
  const [timeframe, setTimeframe] = useState(defaultTimeframe); // Default timeframe
  const [data, setData] = useState([]);
  const [startDate, setStartDate] = useState(new Date(Date.now() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0]);
  const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
  const [error, setError] = useState(null);
  // Fetch data from the backend
  const fetchData = async (ticker, timeframe, startDate, endDate) => {
    try {
      const response = await fetch(`http://127.0.0.1:5000/stock/${ticker}/${startDate}/${endDate}?timeframe=${timeframe}`);
      const responseData = await response.json();
      if (responseData.error) {
        setError(responseData.error);
        throw new Error(responseData.error);
      }
      console.log(data)
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
      const newData = [...formattedData, ...data]
      setData(newData);
    } catch (error) {
      console.error('Error fetching data:', error);
    }
  };

  const requestMore = async () => {
    const newStartDate = new Date(new Date(startDate).getTime() - BAR_LOOKBACK * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const newEndDate = new Date(new Date(startDate).getTime() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    
    console.log(newStartDate, newEndDate)
    try {
      await fetchData(ticker, timeframe,newStartDate,newEndDate);
     
    } catch (error) {
      console.error('Error fetching data:', error);
      setError(error.message);
    }
    setStartDate(newStartDate);
  }

  // Handle search
  const handleSearch = () => {
    if (ticker) {
      fetchData(ticker, timeframe,startDate,endDate);
    } else {
      alert('Please enter a ticker symbol.');
    }
  };

  useEffect(() => {
    fetchData(ticker, timeframe,startDate,endDate);
  }, []);

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
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Enter ticker (e.g., QQQ)"
          className="ticker-input"
        />
        <button onClick={handleSearch} className="search-button">
          Search
        </button>
      </div>
      <div className="chart-container tv-lightweight-charts" ref={chartContainerRef}>
        <ChartComponent data={data} requestMore={requestMore} />
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