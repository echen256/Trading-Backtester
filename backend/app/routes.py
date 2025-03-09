from flask import jsonify, request
import yfinance as yf
from app import app
# Supported timeframes
TIMEFRAMES = {
    '1m': '1m',
    '5m': '5m',
    '15m': '15m',
    '1h': '60m',
    '1d': '1d',
    '1wk': '1wk'
}

@app.route('/stock/<ticker>', methods=['GET'])
def get_stock_data(ticker):
    # Get timeframe from query parameters (default to '1d')
    timeframe = request.args.get('timeframe', '1d')
    
    # Validate timeframe
    if timeframe not in TIMEFRAMES:
        return jsonify(error=f"Invalid timeframe. Supported timeframes are: {list(TIMEFRAMES.keys())}"), 400
    
    # Fetch stock data using yfinance
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period='3y', interval=TIMEFRAMES[timeframe])  # Fetch 1 month of data
        if data.empty:
            return jsonify(error="No data found for the given ticker and timeframe."), 404
        
        # Convert data to JSON
        result = data.reset_index().to_json(orient='records', date_format='iso')
        return jsonify(data=result)
    except Exception as e:
        return jsonify(error=str(e)), 500