import pandas as pd
import pandas_ta as ta
import os

default_indicators = {
    "rsi": {
        "indicator": "rsi", 
        "params": {
            "length": 14,
            "scalar": 100,
            "offset": 0
        }
    },
    "atr": {
        "indicator": "atr",
        "params": {
            "length": 14,
            "scalar": 1,
            "offset": 0
        }
    }
}


def execute_strategy(file_name, start_date, end_date, strategy_name="Default", indicators=['rsi']):
    # Get the correct path to the data directory from the backend root
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.path.join(backend_root, "app", "data_download", "data", "1440", file_name)
    data = pd.read_csv(data_path)

    data.set_index("timestamp", inplace=True)
    
    for indicator in indicators:
        if indicator == "rsi":
            rsi = ta.rsi(data["close"], length=14, scalar=100, offset=0)
            data["rsi"] = rsi
        data.dropna(inplace=True)
        # Create output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", f"strategy_{strategy_name}")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, file_name)
        data.to_csv(output_path, index=True)
    return {"data": data, "indicators": indicators, "strategy_name": strategy_name}

