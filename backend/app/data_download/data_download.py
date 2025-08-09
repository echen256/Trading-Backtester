import pandas as pd
from polygon import RESTClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import json
import argparse
# Load API key from .env file
load_dotenv()
API_KEY = os.getenv('POLYGON_API_KEY')

def download_historical_data(symbol, start_date, end_date, interval='5'):
    """
    Download historical data from Polygon.io
    interval: '1', '5', '15', '30', '60' (minutes)
    """
    client = RESTClient(API_KEY)
    
    # Convert dates to timestamps
    start_ts = int(start_date.timestamp() * 1000)
    end_ts = int(end_date.timestamp() * 1000)
    
    # Get the data
    aggs = client.get_aggs(
        symbol,
        multiplier=int(interval),
        timespan='minute',
        from_=start_ts,
        to=end_ts,
        limit=50000
    )
    
    # Convert to DataFrame
    df = pd.DataFrame(aggs)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['ticker'] = symbol
    return df

def filter_tickers(ticker, config):
    info = requests.get(f'https://api.polygon.io/v3/reference/tickers/{ticker}?apiKey={API_KEY}').json()
    if info['status'] == 'OK':
        if ('market_cap' in info['results']):
            return info['results']['market_cap'] > config['minimum_market_cap']
        else:
            return False
    print(info)
    return False

def download_ticker_data(symbol, config):
    """Download data for a single ticker"""
    interval = 24 * 60  # 1440-minute intervals (daily)
    
    # Define date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5 * 365)  # 5 years of data
    
    # Store all downloaded data
    all_data = []
    
    # Using Method 1: While loop with timedelta
    current_date = start_date
    chunk_size = timedelta(days=30)  # 30-day chunks
    
    while current_date < end_date:
        next_date = min(current_date + chunk_size, end_date)
        print(f"Downloading from {current_date.date()} to {next_date.date()} for {symbol}")
        
        try:
            df = download_historical_data(symbol, current_date, next_date, interval)
            all_data.append(df)
            print(f"Downloaded {len(df)} rows")
        except Exception as e:
            print(f"Error downloading data: {e}")
        
        current_date = next_date

    # Combine all downloaded data
    if all_data:
        final_df = pd.concat(all_data)
        final_df = final_df[~final_df.index.duplicated()]  # Remove any duplicate rows
        
        # Create timeframe-based folder structure
        timeframe_dir = os.path.join('data', str(interval))
        os.makedirs(timeframe_dir, exist_ok=True)
        
        # Save to CSV in timeframe-based folder
        filename = f'{symbol}-{interval}M.csv'
        filepath = os.path.join(timeframe_dir, filename)
        final_df.to_csv(filepath)
        print(f"\nSaved {len(final_df)} total rows to {filepath}")
        return True
    else:
        print("No data was downloaded")
        return False

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Download historical trading data from Polygon.io')
    parser.add_argument('ticker', nargs='?', help='Single ticker to download (e.g., TSLA, AAPL)')
    args = parser.parse_args()

    with open('data_download_config.json', 'r') as file:
        config = json.load(file)

    # If a single ticker is provided, download only that ticker
    if args.ticker:
        ticker = args.ticker.upper()
        print(f"Downloading data for single ticker: {ticker}")
        download_ticker_data(ticker, config)
        return

    # Original logic for downloading all tickers
    with open('tickers.csv', 'r') as file:
        tickers = file.read().splitlines()
        limit = config['limit'] if 'limit' in config else len(tickers)
        count = 0
        print(f"Downloading {limit} tickers")
        
        for symbol in tickers:
            if not filter_tickers(symbol, config):
                continue
            count += 1
            if count > limit:
                break
            
            download_ticker_data(symbol, config)

if __name__ == "__main__":
    main() 