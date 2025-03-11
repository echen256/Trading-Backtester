from flask import jsonify, request
import yfinance as yf
from app import app
import os
import requests
from datetime import datetime, timedelta
# Supported timeframes
TIMEFRAMES = {
    '1m': 'minute',
    '5m': 'minute',
    '15m': 'minute',
    '1h': 'hour',
    '1d': 'day',
    '1wk': 'week'
}

POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', '')
if not POLYGON_API_KEY:
    raise ValueError("POLYGON_API_KEY environment variable is not set")

POLYGON_API = "https://api.polygon.io/v2/aggs/ticker/"

@app.route('/stock/<ticker>', methods=['GET'])
@app.route('/stock/<ticker>/<start_date>/<end_date>', methods=['GET'])
def get_stock_data(ticker, start_date=None, end_date=None):
    # Get timeframe from query parameters (default to '1d')
    timeframe = request.args.get('timeframe', '1d')
    
    # Validate timeframe
    if timeframe not in TIMEFRAMES:
        return jsonify(error=f"Invalid timeframe. Supported timeframes are: {list(TIMEFRAMES.keys())}"), 400
    print(start_date, end_date)
    # Get current date and previous day for the range
    if start_date == 'undefined':
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    if end_date == 'undefined':
        end_date = datetime.now().strftime('%Y-%m-%d') 
    try:
        query_url = f"{POLYGON_API}{ticker}/range/1/{TIMEFRAMES[timeframe]}/{start_date}/{end_date}?apiKey={POLYGON_API_KEY}"
     
        response = requests.get(query_url)
    
        data = response.json()
        if 'resultsCount' not in data or data['resultsCount'] == 0:
            return jsonify(error="No data found for the given ticker and timeframe."), 404
        
        # Return the results
        return jsonify(data=data)
    except Exception as e:
        return jsonify(error=str(e)), 500