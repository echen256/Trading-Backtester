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
from backtesting.execute_strategy import execute_strategy
from backtesting.indicators import BaseIndicator

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
        res = execute_strategy(os.path.basename(csv_path), None, None, "Default", ['rsi', 'atr', 'macd'])
        df = res["data"]
        indicator_objects = res["indicator_objects"]
        strategy_name = res["strategy_name"]
        
        # Convert timestamp to datetime if it exists
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
        
        # Calculate subplot layout based on indicators
        num_indicator_subplots = len([ind for ind in indicator_objects if ind.get_plot_config()["subplot_row"] > 0])
        total_rows = 2 + num_indicator_subplots  # Price + Volume + Indicators
        
        # Create dynamic row heights
        row_heights = [0.5, 0.2] + [0.3 / num_indicator_subplots] * num_indicator_subplots if num_indicator_subplots > 0 else [0.5, 0.5]
        
        # Create subplot titles
        subplot_titles = ['Price Data', 'Volume'] + [ind.get_subplot_title() for ind in indicator_objects if ind.get_plot_config()["subplot_row"] > 0]
        
        fig = make_subplots(
            rows=total_rows, cols=1,
            row_heights=row_heights,
            vertical_spacing=0.08,
            subplot_titles=subplot_titles,
            specs=[[{"secondary_y": False}]] * total_rows
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
        
        # Add indicator plots dynamically
        indicator_subplot_counter = 3  # Start after Price (1) and Volume (2)
        
        for indicator in indicator_objects:
            plot_config = indicator.get_plot_config()
            
            if plot_config["subplot_row"] == 0:
                # Plot on main price chart
                row = 1
            else:
                # Plot on separate subplot
                row = indicator_subplot_counter
                indicator_subplot_counter += 1
            
            if plot_config.get("plot_type") == "multi":
                # Handle multi-trace indicators like MACD
                for trace_config in plot_config["traces"]:
                    column_name = trace_config["column"]
                    if column_name in df.columns:
                        trace_type = trace_config["type"]
                        
                        if trace_type == "line":
                            trace = go.Scatter(
                                x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                                y=df[column_name],
                                mode='lines',
                                name=trace_config["name"],
                                line=dict(color=trace_config["color"], width=trace_config.get("line", {}).get("width", 1))
                            )
                        elif trace_type == "bar":
                            trace = go.Bar(
                                x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                                y=df[column_name],
                                name=trace_config["name"],
                                marker_color=trace_config["color"],
                                opacity=trace_config.get("opacity", 1.0)
                            )
                        
                        fig.add_trace(trace, row=row, col=1)
            else:
                # Handle single-trace indicators
                if indicator.column_name in df.columns:
                    if plot_config["plot_type"] == "line":
                        trace = go.Scatter(
                            x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                            y=df[indicator.column_name],
                            mode='lines',
                            name=indicator.name,
                            line=dict(color=plot_config["color"], width=2),
                            **plot_config.get("additional_config", {})
                        )
                    elif plot_config["plot_type"] == "bar":
                        trace = go.Bar(
                            x=df['timestamp'] if 'timestamp' in df.columns else df.index,
                            y=df[indicator.column_name],
                            name=indicator.name,
                            marker_color=plot_config["color"]
                        )
                    
                    fig.add_trace(trace, row=row, col=1)
                    
                    # Set y-axis range if specified
                    y_range = indicator.get_y_axis_range()
                    if y_range and row > 1:
                        fig.update_yaxes(range=y_range, row=row, col=1)
            
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
        
        # Update axes labels
        fig.update_xaxes(title_text="Time", row=total_rows, col=1)  # Only show time label on bottom subplot
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        
        # Add labels for indicator subplots
        for i, indicator in enumerate([ind for ind in indicator_objects if ind.get_plot_config()["subplot_row"] > 0]):
            fig.update_yaxes(title_text=indicator.name, row=3+i, col=1)
        
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