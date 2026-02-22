from flask import jsonify, request, render_template
from flask_socketio import emit, join_room, leave_room, disconnect
import yfinance as yf
from app import app, socketio
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pathlib import Path
import pandas as pd
import json
import io
from trading_data_pipeline.downloader import download_historical_data
from backtest import execute, save_backtest_results
from config import DEFAULT_DATA_RANGE_YEARS, DATA_DIR, SUPPORTED_TIMEFRAMES
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
        print(e)
        return jsonify(error=str(e)), 500

# WebSocket Events for Trading Data
@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')
    emit('status', {'msg': 'Connected to trading data server'})

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

@socketio.on('join_frontend')
def handle_join_frontend():
    """Frontend clients join this room to receive trading data"""
    join_room('frontend')
    print(f'Frontend client joined: {request.sid}')
    emit('status', {'msg': 'Joined frontend room'})

@socketio.on('join_script')
def handle_join_script():
    """External scripts join this room to send trading data"""
    join_room('script')
    print(f'Script client joined: {request.sid}')
    emit('status', {'msg': 'Joined script room'})

@socketio.on('send_trading_data')
def handle_trading_data(data):
    """
    Receive trading data from external script and relay to frontend
    Expected data format:
    {
        'trades_csv': 'csv_string_data',
        'market_data_csv': 'csv_string_data',
        'timestamp': 'iso_timestamp'
    }
    """
    try:
        print(f'Received trading data from script: {request.sid}')
        
        # Parse CSV data
        trades_df = pd.read_csv(io.StringIO(data.get('trades_csv', '')))
        market_data_df = pd.read_csv(io.StringIO(data.get('market_data_csv', '')))
        
        # Convert DataFrames to JSON for frontend
        processed_data = {
            'trades': trades_df.to_dict('records'),
            'market_data': market_data_df.to_dict('records'),
            'timestamp': data.get('timestamp', datetime.now().isoformat()),
            'trades_count': len(trades_df),
            'market_data_count': len(market_data_df)
        }
        
        # Relay to all frontend clients
        socketio.emit('trading_update', processed_data, room='frontend')
        
        # Confirm receipt to script
        emit('data_received', {
            'status': 'success',
            'trades_processed': len(trades_df),
            'market_data_processed': len(market_data_df)
        })
        
        print(f'Relayed data to frontend: {len(trades_df)} trades, {len(market_data_df)} market data points')
        
    except Exception as e:
        print(f'Error processing trading data: {str(e)}')
        emit('data_received', {
            'status': 'error',
            'message': str(e)
        })

@socketio.on('ping_server')
def handle_ping():
    """Simple ping/pong for connection testing"""
    emit('pong', {'timestamp': datetime.now().isoformat()})

# REST endpoint for sending data (alternative to WebSocket)
@app.route('/api/trading-data', methods=['POST'])
def receive_trading_data():
    """
    REST alternative for sending trading data
    Expects form data with 'trades_csv' and 'market_data_csv' files
    """
    try:
        trades_file = request.files.get('trades_csv')
        market_data_file = request.files.get('market_data_csv')
        
        if not trades_file or not market_data_file:
            return jsonify({'error': 'Both trades_csv and market_data_csv files required'}), 400
        
        # Read CSV files
        trades_df = pd.read_csv(trades_file)
        market_data_df = pd.read_csv(market_data_file)
        
        # Prepare data for frontend
        processed_data = {
            'trades': trades_df.to_dict('records'),
            'market_data': market_data_df.to_dict('records'),
            'timestamp': datetime.now().isoformat(),
            'trades_count': len(trades_df),
            'market_data_count': len(market_data_df)
        }
        
        # Send to frontend clients via WebSocket
        socketio.emit('trading_update', processed_data, room='frontend')
        
        return jsonify({
            'status': 'success',
            'trades_processed': len(trades_df),
            'market_data_processed': len(market_data_df)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_historical_data')
def download_historical_data_route():
    """
    Download historical data for a given symbol
    Query parameters:
    - symbol: Stock symbol (required)
    - start_date: Start date (optional, defaults to 10 years ago)
    - end_date: End date (optional, defaults to today)
    - interval: Time interval in minutes (optional, defaults to 5)
    """
    try:
        # Get query parameters
        symbol = request.args.get('symbol')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        interval = request.args.get('interval', '5')
        
        if not symbol:
            return jsonify({'error': 'Symbol parameter is required'}), 400
        
        # Set default dates if not provided
        if not end_date:
            end_date = datetime.now()
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
            
        if not start_date:
            start_date = end_date - timedelta(days=365 * DEFAULT_DATA_RANGE_YEARS)
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        
        # Download the data
        df = download_historical_data(symbol, start_date, end_date, interval)
        
        # Save to CSV in data directory
        os.makedirs(DATA_DIR, exist_ok=True)
        filename = f"{symbol}_{interval}m.csv"
        filepath = os.path.join(DATA_DIR, filename)
        df.to_csv(filepath)
        
        return jsonify({
            'status': 'success',
            'message': f'Downloaded {len(df)} data points for {symbol}',
            'filename': filename,
            'filepath': filepath,
            'data_points': len(df),
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'interval': interval
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/execute_backtest')
def execute_backtest_route():
    """
    Execute a backtest for a given strategy
    Query parameters:
    - strategy_name: Name of the strategy (required)
    - ticker: Stock ticker symbol (required)
    - timeframe: Time interval (required)
    - start_date: Start date (required)
    - end_date: End date (required)
    """
    try:
        # Get query parameters
        strategy_name = request.args.get('strategy_name')
        ticker = request.args.get('ticker')
        timeframe = request.args.get('timeframe')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Validate required parameters
        if not all([strategy_name, ticker, timeframe, start_date, end_date]):
            return jsonify({
                'error': 'All parameters are required: strategy_name, ticker, timeframe, start_date, end_date'
            }), 400
        
        # Validate timeframe
        if timeframe not in SUPPORTED_TIMEFRAMES:
            return jsonify({
                'error': f'Invalid timeframe. Supported timeframes: {SUPPORTED_TIMEFRAMES}'
            }), 400
        
        # Parse dates
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
        
        # Check if data file exists
        interval = timeframe.replace('m', '')  # Convert 5m to 5
        data_filename = f"{ticker}_{interval}m.csv"
        data_filepath = os.path.join(DATA_DIR, data_filename)
        
        if not os.path.exists(data_filepath):
            # Download data if it doesn't exist
            try:
                df = download_historical_data(ticker, start_date_obj, end_date_obj, interval)
                os.makedirs(DATA_DIR, exist_ok=True)
                df.to_csv(data_filepath)
                download_message = f"Downloaded {len(df)} data points for {ticker}"
            except Exception as e:
                return jsonify({'error': f'Failed to download data: {str(e)}'}), 500
        else:
            download_message = f"Using existing data file: {data_filename}"
        
        # Execute the backtest
        backtest_results = execute()
        
        # Save results
        results_filepath = save_backtest_results(
            strategy_name, ticker, start_date, end_date, timeframe, backtest_results
        )
        
        return jsonify({
            'status': 'success',
            'message': 'Backtest executed successfully',
            'download_message': download_message,
            'data_file': data_filepath,
            'results_file': results_filepath,
            'strategy_name': strategy_name,
            'ticker': ticker,
            'timeframe': timeframe,
            'start_date': start_date,
            'end_date': end_date,
            'results': backtest_results
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def dashboard():
    """Serve the trading dashboard"""
    return render_template('dashboard.html')

# 
