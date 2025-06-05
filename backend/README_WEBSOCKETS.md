# Trading WebSocket System

A real-time trading dashboard system that allows external scripts to send CSV data (trades and market data) to a web frontend via WebSocket connections.

## 🚀 Features

- **Real-time Data Streaming**: External scripts can send trading data in real-time
- **WebSocket Communication**: Bi-directional communication between scripts and frontend
- **CSV Data Support**: Handles two types of CSV data - trades and market data
- **Live Dashboard**: Beautiful web interface showing real-time updates
- **REST API Alternative**: HTTP endpoint for sending data when WebSockets aren't suitable

## 📋 Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the Server

```bash
python app.py
```

The server will start on `http://localhost:5000`

### 3. Access the Dashboard

Open your browser and go to `http://localhost:5000` to see the live trading dashboard.

## 📡 WebSocket API

### Connection Events

#### For Frontend Clients:
- `connect` - Automatically connects to the server
- `join_frontend` - Join the frontend room to receive trading updates
- `trading_update` - Receives new trading data
- `status` - Receives connection status messages

#### For External Scripts:
- `connect` - Automatically connects to the server  
- `join_script` - Join the script room to send trading data
- `send_trading_data` - Send CSV data to the server
- `data_received` - Confirmation that data was processed

### Data Format

When sending data via `send_trading_data`, use this format:

```json
{
    "trades_csv": "timestamp,symbol,side,quantity,price,profit_loss,strategy\n2023-01-01T10:00:00,AAPL,BUY,100,150.00,25.50,Strategy1",
    "market_data_csv": "timestamp,symbol,open,high,low,close,volume,rsi,signal_strength\n2023-01-01T10:00:00,AAPL,149.50,151.00,149.00,150.00,50000,65.5,0.75",
    "timestamp": "2023-01-01T10:00:00"
}
```

## 🛠️ Usage Examples

### Using the Example Script

Run the provided example script to see the system in action:

```bash
python example_script.py
```

This will:
1. Connect to the WebSocket server
2. Send sample trading data every 10 seconds
3. Display confirmation messages
4. Automatically disconnect after 5 updates

### Custom Script Integration

```python
import socketio
import pandas as pd
from datetime import datetime

# Create client
sio = socketio.Client()

# Connect to server
sio.connect('http://localhost:5000')

# Join script room
sio.emit('join_script')

# Send your data
trades_df = pd.read_csv('your_trades.csv')
market_df = pd.read_csv('your_market_data.csv')

data = {
    'trades_csv': trades_df.to_csv(index=False),
    'market_data_csv': market_df.to_csv(index=False),
    'timestamp': datetime.now().isoformat()
}

sio.emit('send_trading_data', data)
```

## 🌐 REST API Alternative

If WebSockets aren't suitable, you can use the REST endpoint:

```bash
curl -X POST http://localhost:5000/api/trading-data \
  -F "trades_csv=@trades.csv" \
  -F "market_data_csv=@market_data.csv"
```

## 📊 Expected CSV Formats

### Trades CSV
```csv
timestamp,symbol,side,quantity,price,profit_loss,strategy
2023-01-01T10:00:00,AAPL,BUY,100,150.00,25.50,Three Red Bodies
2023-01-01T10:05:00,TSLA,SELL,50,800.00,-15.25,Three Red Bodies
```

### Market Data CSV
```csv
timestamp,symbol,open,high,low,close,volume,rsi,signal_strength
2023-01-01T10:00:00,AAPL,149.50,151.00,149.00,150.00,50000,65.5,0.75
2023-01-01T10:05:00,TSLA,799.00,805.00,795.00,800.00,25000,45.2,0.85
```

## 🎯 Dashboard Features

The web dashboard displays:

- **Connection Status**: Shows if the WebSocket connection is active
- **Real-time Stats**: Total trades, data points, and last update time
- **Live Trades Table**: Recent trades with buy/sell indicators and P&L
- **Market Data Table**: Real-time market data with OHLC and technical indicators
- **Responsive Design**: Works on desktop and mobile devices

## 🔧 Configuration

### Server Configuration

Edit `app/__init__.py` to modify:
- CORS settings
- Secret key
- WebSocket configuration

### Frontend Customization

The dashboard template is in `templates/dashboard.html` and can be customized:
- Styling and colors
- Data display format
- Additional charts or indicators
- Refresh intervals

## 🚨 Troubleshooting

### Common Issues:

1. **Connection Refused**: Make sure the server is running on port 5000
2. **CORS Errors**: Check CORS settings in `app/__init__.py`
3. **CSV Parsing Errors**: Ensure your CSV data matches the expected format
4. **Missing Dependencies**: Run `pip install -r requirements.txt`

### Debug Mode:

The server runs in debug mode by default. Check the console for detailed error messages.

## 📈 Integration with Trading Systems

This system is designed to integrate with:
- Algorithmic trading bots
- Market data providers
- Backtesting systems
- Risk management tools
- Portfolio management systems

Simply have your trading system send CSV data to the WebSocket server, and the dashboard will display it in real-time.

## 🔒 Security Notes

- The current setup allows all CORS origins (for development)
- Add authentication for production use
- Consider rate limiting for high-frequency data
- Validate CSV data format before processing

## 📝 License

This is part of the Trading Backtester project. Use according to your project's license terms. 