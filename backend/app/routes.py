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

@app.route('/')
def dashboard():
    """Serve the trading dashboard"""
    return render_template('dashboard.html')

# 