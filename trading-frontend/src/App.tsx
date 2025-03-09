import { useRef, useState } from 'react';
import './App.css';
import { ChartComponent } from './components/Chart';

function App() {
  const chartContainerRef = useRef(null);
  const [ticker, setTicker] = useState('BTC-USD');
  const [timeframe, setTimeframe] = useState('15m'); // Default timeframe
  const [data, setData] = useState([]);

  // Fetch data from the backend
  const fetchData = async (ticker, timeframe) => {
    try {
      const response = await fetch(`http://127.0.0.1:5000/stock/${ticker}?timeframe=${timeframe}`);
      const data = await response.json();
      if (data.error) {
        alert(data.error);
        return;
      }
      const parsedData = JSON.parse(data.data);
      console.log(parsedData)
      const formattedData = parsedData.map((item) => ({
        time: new Date(item.Datetime || item.Date).getTime(),
        open: item.Open,
        high: item.High,
        low: item.Low,
        close: item.Close,
        volume: item.Volume,
      }));
      console.log(formattedData)
      setData(formattedData);
    } catch (error) {
      console.error('Error fetching data:', error);
      alert('Failed to fetch data. Please try again.');
    }
  };

  // Handle search
  const handleSearch = () => {
    if (ticker) {
      fetchData(ticker, timeframe);
    } else {
      alert('Please enter a ticker symbol.');
    }
  };

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
          placeholder="Enter ticker (e.g., BTC-USD)"
          className="ticker-input"
        />
        <button onClick={handleSearch} className="search-button">
          Search
        </button>
      </div>
      <div className="chart-container tv-lightweight-charts" ref={chartContainerRef}>
        <ChartComponent data={data} />
      </div>
    </div>
  );
}

export default App;