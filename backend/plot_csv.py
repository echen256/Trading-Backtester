#!/usr/bin/env python3
"""
Simple Plotly visualization script for CSV files in trading-backtester data directory.
Usage: python plot_csv.py [csv_file_path]
If no path provided, uses TSLA-1440M.csv by default.
"""

import sys
import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from backtesting.execute_strategy import default_indicators, execute_strategy

def find_csv_files():
    """Find available CSV files in the data directory"""
    data_dir = "./app/data_download/data"
    csv_files = []
    
    if os.path.exists(data_dir):
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                if file.endswith('.csv'):
                    csv_files.append(os.path.join(root, file))
    
    return csv_files

def plot_trading_data(csv_path):
    """Create Plotly visualization for trading CSV data"""
    try:
        # Call execute_strategy with proper parameters
        res = execute_strategy(os.path.basename(csv_path), None, None, "Default", ['rsi'])
        df = res["data"]
        indicators = res["indicators"]
        strategy_name = res["strategy_name"]
        
        # Convert timestamp to datetime if it exists
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
        
        # Create subplot with secondary y-axis for volume
        fig = make_subplots(
            rows=len(indicators) + 2, cols=1,
            row_heights= [0.5, 0.25, 0.25],
            vertical_spacing=0.1,
            subplot_titles=('Price Data', 'Volume', "RSI"),
            specs=[[{"secondary_y": False}],
                   [{"secondary_y": False}],
                   [{"secondary_y": False}]
                   ]
        )
        
        # Add candlestick chart if OHLC data is available
        if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            fig.add_trace(
                go.Candlestick(
                    x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                    open=df['open'],
                    high=df['high'],
                    low=df['low'],
                    close=df['close'],
                    name="OHLC"
                ),
                row=1, col=1
            )
        elif 'close' in df.columns:
            # Fallback to line chart for close price
            fig.add_trace(
                go.Scatter(
                    x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                    y=df['close'],
                    mode='lines',
                    name='Close Price'
                ),
                row=1, col=1
            )
        
        # Add volume chart if available
        if 'volume' in df.columns:
            fig.add_trace(
                go.Bar(
                    x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                    y=df['volume'],
                    name='Volume',
                    marker_color='rgba(0,0,255,0.3)'
                ),
                row=2, col=1
            )
        
        if ('rsi' in df.columns):
            fig.add_trace(
                go.Line(
                    x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                    y=df['rsi'],
                    name='RSI'
                ),
                row=3, col=1
            )
            
            # Update layout - safely get ticker
            
        ticker = 'Unknown'
        if 'ticker' in df.columns and len(df) > 0:
            ticker = df['ticker'].iloc[0]
        elif len(df) > 0:
            # Try to extract ticker from filename
            ticker = os.path.basename(csv_path).split('-')[0] if '-' in os.path.basename(csv_path) else 'Unknown'
        fig.update_layout(
            title=f'{ticker} Trading Data Visualization',
            xaxis_rangeslider_visible=False,
            height=800,
            showlegend=True
        )
        
        fig.update_xaxes(title_text="Time", row=2, col=1)
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        
        fig.show()
        
    except Exception as e:
        print(f"Error plotting data: {e}")
        print(f"Available columns: {df.columns.tolist() if 'df' in locals() else 'Could not read file'}")

def main():
    # Default CSV file
    default_path = "./app/data_download/data/1440"
    default_csv = "TSLA-1440M.csv"
    
    # Use provided path or default
    csv_path =   sys.argv[1] if len(sys.argv) > 1 else default_csv
 
    plot_trading_data(csv_path)

if __name__ == "__main__":
    main()