# Requested Backend Changes: Functional Backtesting Architecture

## Overview

Based on the existing `run.py` template, this document outlines a functional programming approach for a comprehensive backtesting system that supports various trading strategies, takes CSV files as input, and outputs trade lists and portfolio performance metrics.

## Current Architecture Analysis

### Existing Components
- **run.py**: Single-file backtest with hardcoded TSLA data and ML model
- **backtest.py**: Placeholder with result saving infrastructure
- **config.py**: Basic configuration for timeframes and directories
- **Data Structure**: CSV format with OHLCV + timestamp, volume, vwap, transactions

### Current Limitations
- Hardcoded strategy and data source
- No abstraction for different strategy types
- Limited portfolio metrics output
- No strategy parameter optimization
- Single timeframe support per run

## Proposed Functional Architecture

### 1. Core Components

#### Strategy Functions
```python
# strategies/ml_strategy.py
def create_ml_strategy(model_path, probability_threshold=0.3, indicators=None):
    """Returns a strategy function configured with ML model parameters"""
    model = joblib.load(model_path)
    indicators = indicators or ['rsi', 'atr', 'ift_rsi']
    
    def ml_strategy(data, current_idx):
        # Extract features and generate signals
        features = extract_features(data, indicators, current_idx)
        if features is None:
            return None
        
        proba = model.predict_proba([features])[0, 1]
        signal_strength = proba if proba > probability_threshold else 0
        
        return {
            'signal': 'short' if signal_strength > 0 else None,
            'strength': signal_strength,
            'entry_price': data.iloc[current_idx]['close'],
            'timestamp': data.index[current_idx]
        }
    
    return ml_strategy

# strategies/technical_strategy.py
def create_rsi_strategy(period=14, oversold=30, overbought=70):
    """Returns RSI mean reversion strategy function"""
    def rsi_strategy(data, current_idx):
        if current_idx < period:
            return None
            
        rsi_values = calculate_rsi(data['close'], period)
        current_rsi = rsi_values.iloc[current_idx]
        
        if current_rsi < oversold:
            return {
                'signal': 'long',
                'strength': (oversold - current_rsi) / oversold,
                'entry_price': data.iloc[current_idx]['close'],
                'timestamp': data.index[current_idx]
            }
        elif current_rsi > overbought:
            return {
                'signal': 'short', 
                'strength': (current_rsi - overbought) / (100 - overbought),
                'entry_price': data.iloc[current_idx]['close'],
                'timestamp': data.index[current_idx]
            }
        return None
    
    return rsi_strategy

# strategies/pattern_strategy.py
def create_pattern_strategy(pattern_name, lookback_periods=3):
    """Returns pattern recognition strategy function"""
    def pattern_strategy(data, current_idx):
        if current_idx < lookback_periods:
            return None
            
        pattern_detected = detect_pattern(data, current_idx, pattern_name, lookback_periods)
        
        if pattern_detected:
            return {
                'signal': pattern_detected['direction'],
                'strength': pattern_detected['confidence'],
                'entry_price': data.iloc[current_idx]['close'],
                'timestamp': data.index[current_idx]
            }
        return None
    
    return pattern_strategy
```

#### Data Processing Functions
```python
# data/data_utils.py
def load_csv_data(filepath, start_date=None, end_date=None):
    """Load and validate CSV data with optional date filtering"""
    data = pd.read_csv(filepath, index_col=0, parse_dates=True)
    
    # Validate required columns
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    validate_data_format(data, required_cols)
    
    # Filter by date range if provided
    if start_date:
        data = data[data.index >= start_date]
    if end_date:
        data = data[data.index <= end_date]
    
    return data

def validate_data_format(data, required_columns):
    """Validate data has required columns and proper format"""
    missing_cols = [col for col in required_columns if col not in data.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Check for missing values
    if data[required_columns].isnull().any().any():
        raise ValueError("Data contains missing values in required columns")
    
    return True

def resample_timeframe(data, target_timeframe):
    """Resample data to target timeframe"""
    agg_dict = {
        'open': 'first',
        'high': 'max', 
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    return data.resample(target_timeframe).agg(agg_dict).dropna()

def add_technical_indicators(data, indicators):
    """Add technical indicators to data"""
    result = data.copy()
    
    for indicator in indicators:
        if indicator == 'rsi':
            result['rsi'] = calculate_rsi(data['close'], 14)
        elif indicator == 'atr':
            result['atr'] = calculate_atr(data, 14)
        elif indicator == 'ift_rsi':
            rsi = calculate_rsi(data['close'], 14)
            result['ift_rsi'] = calculate_ift(rsi)
    
    return result
```

#### Portfolio Management Functions
```python
# portfolio/portfolio_utils.py
def create_portfolio_state(initial_capital=100000, commission_rate=0.001, slippage=0.0005):
    """Create initial portfolio state"""
    return {
        'cash': initial_capital,
        'positions': {},
        'trades': [],
        'portfolio_values': [],
        'commission_rate': commission_rate,
        'slippage': slippage
    }

def execute_trade(portfolio_state, signal, current_price, timestamp, position_size_func):
    """Execute a trade and update portfolio state"""
    if signal is None:
        return portfolio_state
    
    # Calculate position size
    position_size = position_size_func(portfolio_state, signal, current_price)
    
    # Apply slippage and commission
    execution_price = apply_slippage_and_commission(
        current_price, signal['signal'], portfolio_state['slippage'], portfolio_state['commission_rate']
    )
    
    # Create trade record
    trade = {
        'timestamp': timestamp,
        'signal': signal['signal'],
        'quantity': position_size,
        'entry_price': execution_price,
        'signal_strength': signal['strength']
    }
    
    # Update portfolio state
    portfolio_state['cash'] -= position_size * execution_price
    portfolio_state['positions'][timestamp] = trade
    portfolio_state['trades'].append(trade)
    
    return portfolio_state

def calculate_position_size(portfolio_state, signal, current_price, risk_per_trade=0.02):
    """Calculate position size based on risk management"""
    available_cash = portfolio_state['cash']
    max_risk_amount = available_cash * risk_per_trade
    
    # Simple position sizing - can be enhanced with volatility-based sizing
    position_value = min(max_risk_amount * 10, available_cash * 0.1)  # Max 10% of portfolio
    return int(position_value / current_price)

def update_portfolio_value(portfolio_state, current_prices, timestamp):
    """Update portfolio value with current market prices"""
    cash = portfolio_state['cash']
    positions_value = sum(
        trade['quantity'] * current_prices.get(trade['timestamp'], trade['entry_price'])
        for trade in portfolio_state['positions'].values()
    )
    
    total_value = cash + positions_value
    portfolio_state['portfolio_values'].append({
        'timestamp': timestamp,
        'value': total_value,
        'cash': cash,
        'positions_value': positions_value
    })
    
    return total_value
```

#### Risk Management Functions
```python
# portfolio/risk_utils.py
def check_position_limits(portfolio_state, new_position_size, max_position_pct=0.1):
    """Check if new position exceeds limits"""
    total_value = portfolio_state['cash'] + sum(
        trade['quantity'] * trade['entry_price'] for trade in portfolio_state['positions'].values()
    )
    
    max_position_value = total_value * max_position_pct
    return new_position_size <= max_position_value

def calculate_stop_loss(entry_price, direction, stop_loss_pct=0.02):
    """Calculate stop loss price"""
    if direction == 'long':
        return entry_price * (1 - stop_loss_pct)
    else:  # short
        return entry_price * (1 + stop_loss_pct)

def check_drawdown_limits(portfolio_values, max_drawdown=0.2):
    """Check if current drawdown exceeds limits"""
    if len(portfolio_values) < 2:
        return True
    
    values = [pv['value'] for pv in portfolio_values]
    peak = max(values)
    current = values[-1]
    drawdown = (peak - current) / peak
    
    return drawdown <= max_drawdown
```

### 2. Main Backtesting Engine

```python
# backtest_engine.py
def run_backtest(csv_filepath, strategy_func, config=None):
    """
    Main backtesting function that orchestrates the entire process
    
    Args:
        csv_filepath: Path to CSV data file
        strategy_func: Strategy function that generates signals
        config: Configuration dictionary with backtest parameters
    
    Returns:
        dict: Contains trades, portfolio_values, and performance metrics
    """
    # Load configuration
    config = config or get_default_config()
    
    # Load and prepare data
    data = load_csv_data(csv_filepath, config.get('start_date'), config.get('end_date'))
    
    # Add technical indicators if required
    if config.get('indicators'):
        data = add_technical_indicators(data, config['indicators'])
    
    # Initialize portfolio
    portfolio_state = create_portfolio_state(
        initial_capital=config.get('initial_capital', 100000),
        commission_rate=config.get('commission_rate', 0.001),
        slippage=config.get('slippage', 0.0005)
    )
    
    # Position sizing function
    position_size_func = lambda ps, sig, price: calculate_position_size(
        ps, sig, price, config.get('risk_per_trade', 0.02)
    )
    
    # Run backtest loop
    for i in range(len(data)):
        timestamp = data.index[i]
        current_price = data.iloc[i]['close']
        
        # Generate signal
        signal = strategy_func(data, i)
        
        # Execute trade if signal exists
        if signal:
            portfolio_state = execute_trade(
                portfolio_state, signal, current_price, timestamp, position_size_func
            )
        
        # Update portfolio value
        update_portfolio_value(portfolio_state, {'current': current_price}, timestamp)
    
    # Calculate performance metrics
    performance_metrics = calculate_performance_metrics(
        portfolio_state['trades'], 
        portfolio_state['portfolio_values']
    )
    
    return {
        'trades': portfolio_state['trades'],
        'portfolio_values': portfolio_state['portfolio_values'],
        'performance': performance_metrics
    }
```

#### Performance Analysis Functions
```python
# results/performance_utils.py
def calculate_performance_metrics(trades, portfolio_values):
    """Calculate comprehensive performance metrics"""
    if not trades or not portfolio_values:
        return {}
    
    # Basic metrics
    total_trades = len(trades)
    winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
    losing_trades = [t for t in trades if t.get('pnl', 0) < 0]
    
    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
    avg_win = sum(t['pnl'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t['pnl'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
    
    # Portfolio metrics
    values = [pv['value'] for pv in portfolio_values]
    returns = calculate_returns(values)
    
    total_return = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0
    sharpe_ratio = calculate_sharpe_ratio(returns)
    max_drawdown = calculate_max_drawdown(values)
    
    return {
        'total_return': total_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'win_rate': win_rate,
        'total_trades': total_trades,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0
    }

def calculate_returns(values):
    """Calculate returns from portfolio values"""
    if len(values) < 2:
        return []
    return [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values))]

def calculate_sharpe_ratio(returns, risk_free_rate=0.02):
    """Calculate Sharpe ratio"""
    if not returns:
        return 0
    
    mean_return = sum(returns) / len(returns)
    std_return = (sum((r - mean_return) ** 2 for r in returns) / len(returns)) ** 0.5
    
    return (mean_return - risk_free_rate / 252) / std_return if std_return > 0 else 0

def calculate_max_drawdown(values):
    """Calculate maximum drawdown"""
    if len(values) < 2:
        return 0
    
    peak = values[0]
    max_dd = 0
    
    for value in values[1:]:
        if value > peak:
            peak = value
        else:
            drawdown = (peak - value) / peak
            max_dd = max(max_dd, drawdown)
    
    return max_dd
```

#### Output Generation Functions
```python
# results/output_utils.py
def save_trades_csv(trades, filepath):
    """Save trades to CSV file"""
    import csv
    
    fieldnames = ['timestamp', 'symbol', 'side', 'quantity', 'entry_price', 'exit_price', 
                  'pnl', 'duration', 'strategy', 'signal_strength']
    
    with open(filepath, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for trade in trades:
            writer.writerow({
                'timestamp': trade['timestamp'],
                'symbol': trade.get('symbol', 'UNKNOWN'),
                'side': trade['signal'],
                'quantity': trade['quantity'],
                'entry_price': trade['entry_price'],
                'exit_price': trade.get('exit_price', ''),
                'pnl': trade.get('pnl', ''),
                'duration': trade.get('duration', ''),
                'strategy': trade.get('strategy', 'UNKNOWN'),
                'signal_strength': trade.get('signal_strength', '')
            })

def save_performance_json(performance_metrics, filepath):
    """Save performance metrics to JSON file"""
    import json
    
    with open(filepath, 'w') as f:
        json.dump(performance_metrics, f, indent=2, default=str)

def save_equity_curve_data(portfolio_values, filepath):
    """Save equity curve data for visualization"""
    import csv
    
    with open(filepath, 'w', newline='') as csvfile:
        fieldnames = ['timestamp', 'portfolio_value', 'cash', 'positions_value']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for pv in portfolio_values:
            writer.writerow(pv)
```

### 3. Configuration System

```python
# config/strategy_configs.py
def get_strategy_config(strategy_name):
    """Get configuration for a specific strategy"""
    configs = {
        'ml_pattern': {
            'model_path': 'v2.joblib',
            'probability_threshold': 0.3,
            'indicators': ['rsi', 'atr', 'ift_rsi']
        },
        'rsi_mean_reversion': {
            'rsi_period': 14,
            'oversold_threshold': 30,
            'overbought_threshold': 70
        },
        'three_red_bodies': {
            'lookback_periods': 3,
            'min_body_size': 0.001
        }
    }
    return configs.get(strategy_name, {})

# config/backtest_configs.py
def get_default_config():
    """Get default backtesting configuration"""
    return {
        'initial_capital': 100000,
        'commission_rate': 0.001,
        'slippage': 0.0005,
        'risk_per_trade': 0.02,
        'max_position_size': 0.1,
        'max_drawdown': 0.2,
        'indicators': ['rsi', 'atr']
    }

def load_config_from_file(filepath):
    """Load configuration from JSON file"""
    import json
    
    with open(filepath, 'r') as f:
        return json.load(f)
```

### 4. Strategy Factory Function

```python
# strategies/strategy_factory.py
def create_strategy(strategy_name, **kwargs):
    """Factory function to create strategy functions"""
    config = get_strategy_config(strategy_name)
    config.update(kwargs)
    
    if strategy_name == 'ml_pattern':
        return create_ml_strategy(
            config['model_path'],
            config['probability_threshold'],
            config['indicators']
        )
    elif strategy_name == 'rsi_mean_reversion':
        return create_rsi_strategy(
            config['rsi_period'],
            config['oversold_threshold'],
            config['overbought_threshold']
        )
    elif strategy_name == 'three_red_bodies':
        return create_pattern_strategy(
            'three_red_bodies',
            config['lookback_periods']
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")
```

## Required Changes

### 1. File Structure Additions

```
backend/
├── strategies/
│   ├── __init__.py
│   ├── ml_strategy.py
│   ├── technical_strategy.py
│   ├── pattern_strategy.py
│   └── strategy_factory.py
├── data/
│   ├── __init__.py
│   └── data_utils.py
├── portfolio/
│   ├── __init__.py
│   ├── portfolio_utils.py
│   └── risk_utils.py
├── results/
│   ├── __init__.py
│   ├── performance_utils.py
│   └── output_utils.py
├── config/
│   ├── __init__.py
│   ├── strategy_configs.py
│   └── backtest_configs.py
├── backtest_engine.py
└── run_backtest.py (new main entry point)
```

### 2. Enhanced backtest.py

Replace the current placeholder with functional backtesting logic:
- Pure function-based approach
- Strategy function composition
- Immutable data structures where possible
- Configurable parameters via functions

### 3. New Dependencies

Add to requirements.txt:
```
ta-lib  # Technical analysis library
matplotlib  # For plotting equity curves
seaborn  # Enhanced visualizations
```

### 4. CLI Interface

```python
# run_backtest.py
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Run functional backtesting')
    parser.add_argument('--csv', required=True, help='Path to CSV data file')
    parser.add_argument('--strategy', required=True, help='Strategy name')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--config', help='Path to custom config file')
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config_from_file(args.config) if args.config else get_default_config()
    if args.start_date:
        config['start_date'] = args.start_date
    if args.end_date:
        config['end_date'] = args.end_date
    
    # Create strategy function
    strategy_func = create_strategy(args.strategy)
    
    # Run backtest
    results = run_backtest(args.csv, strategy_func, config)
    
    # Save outputs
    save_trades_csv(results['trades'], f'trades_{args.strategy}.csv')
    save_performance_json(results['performance'], f'performance_{args.strategy}.json')
    save_equity_curve_data(results['portfolio_values'], f'equity_curve_{args.strategy}.csv')
    
    print(f"Backtest completed. Results saved with prefix: {args.strategy}")

if __name__ == '__main__':
    main()
```

### 5. Output Format Specifications

#### Trade List CSV Format
```
timestamp,symbol,side,quantity,entry_price,exit_price,pnl,duration,strategy,signal_strength
2024-06-04 18:23:00,TSLA,short,100,176.52,176.33,19.00,5min,ml_pattern,0.65
```

#### Performance JSON Format
```json
{
  "summary": {
    "total_return": 0.15,
    "sharpe_ratio": 1.2,
    "max_drawdown": 0.08,
    "win_rate": 0.58,
    "profit_factor": 1.35
  },
  "trades": {
    "total_trades": 45,
    "winning_trades": 26,
    "losing_trades": 19,
    "avg_win": 120.50,
    "avg_loss": -85.30
  },
  "monthly_returns": [
    {"month": "2024-06", "return": 0.03},
    {"month": "2024-07", "return": 0.02}
  ]
}
```

## Implementation Priority

1. **High Priority**: Core engine and strategy framework
2. **Medium Priority**: Enhanced analytics and risk management
3. **Low Priority**: Advanced optimization and visualization features

## Integration with Existing System

- Maintain compatibility with current WebSocket architecture
- Integrate with existing Flask routes for backtest execution
- Use existing results directory structure
- Preserve current model loading mechanism for ML strategies

## Testing Requirements

- Unit tests for each strategy class
- Integration tests for full backtest runs
- Performance tests with large datasets
- Data validation tests for various CSV formats

This architecture provides a flexible, extensible foundation for various backtesting strategies while maintaining compatibility with the existing system.