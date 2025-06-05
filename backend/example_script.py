#!/usr/bin/env python3
"""
Example external script that sends trading data to the WebSocket server
This demonstrates how to integrate with the trading dashboard system
"""

import socketio
import pandas as pd
import time
import random
from datetime import datetime, timedelta
import numpy as np

# Create SocketIO client
sio = socketio.Client()

# Server URL
SERVER_URL = 'http://localhost:5000'

@sio.event
def connect():
    print('Connected to server')
    # Join the script room
    sio.emit('join_script')

@sio.event
def disconnect():
    print('Disconnected from server')

@sio.event
def data_received(data):
    print(f"Server confirmed data receipt: {data}")

@sio.event
def status(data):
    print(f"Status: {data['msg']}")

def generate_sample_trades(num_trades=5):
    """Generate sample trade data"""
    trades = []
    for i in range(num_trades):
        trade = {
            'timestamp': (datetime.now() - timedelta(minutes=random.randint(1, 60))).isoformat(),
            'symbol': random.choice(['AAPL', 'TSLA', 'MSFT', 'GOOGL', 'AMZN']),
            'side': random.choice(['BUY', 'SELL']),
            'quantity': random.randint(10, 1000),
            'price': round(random.uniform(100, 500), 2),
            'profit_loss': round(random.uniform(-100, 100), 2),
            'strategy': 'Three Red Bodies'
        }
        trades.append(trade)
    return pd.DataFrame(trades)

def generate_sample_market_data(num_points=20):
    """Generate sample market data"""
    base_price = 300
    data = []
    
    for i in range(num_points):
        timestamp = datetime.now() - timedelta(minutes=num_points-i)
        price = base_price + random.uniform(-5, 5)
        
        point = {
            'timestamp': timestamp.isoformat(),
            'symbol': 'TSLA',
            'open': round(price + random.uniform(-1, 1), 2),
            'high': round(price + random.uniform(0, 2), 2),
            'low': round(price - random.uniform(0, 2), 2),
            'close': round(price, 2),
            'volume': random.randint(10000, 100000),
            'rsi': round(random.uniform(20, 80), 2),
            'signal_strength': round(random.uniform(0, 1), 3)
        }
        data.append(point)
        base_price = price
        
    return pd.DataFrame(data)

def send_trading_data():
    """Send sample trading data to the server"""
    try:
        # Generate sample data
        trades_df = generate_sample_trades()
        market_data_df = generate_sample_market_data()
        
        # Convert to CSV strings
        trades_csv = trades_df.to_csv(index=False)
        market_data_csv = market_data_df.to_csv(index=False)
        
        # Prepare data payload
        data_payload = {
            'trades_csv': trades_csv,
            'market_data_csv': market_data_csv,
            'timestamp': datetime.now().isoformat()
        }
        
        # Send to server
        print(f"Sending {len(trades_df)} trades and {len(market_data_df)} market data points...")
        sio.emit('send_trading_data', data_payload)
        
    except Exception as e:
        print(f"Error sending data: {e}")

def main():
    """Main function to connect and send data periodically"""
    try:
        # Connect to server
        print(f"Connecting to {SERVER_URL}...")
        sio.connect(SERVER_URL)
        
        # Send data every 10 seconds for demo
        for i in range(5):  # Send 5 updates then stop
            print(f"\n--- Update {i+1} ---")
            send_trading_data()
            
            if i < 4:  # Don't sleep after last iteration
                print("Waiting 10 seconds before next update...")
                time.sleep(10)
        
        print("\nDemo completed. Disconnecting...")
        sio.disconnect()
        
    except Exception as e:
        print(f"Connection error: {e}")
    except KeyboardInterrupt:
        print("\nInterrupted by user. Disconnecting...")
        sio.disconnect()

if __name__ == '__main__':
    main() 