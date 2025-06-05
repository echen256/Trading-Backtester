import vectorbt as vbt
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier
import joblib
import os

df = pd.read_csv('./data/TSLA_5m.csv', index_col=0, parse_dates=True)
# Extract price data
price = df['close']
open_ = df['open']
high = df['high']
low = df['low']

body     = (price - open_).abs()
down_3   = (price < price.shift(1)) & (price.shift(1) < price.shift(2))
bigger   = (body > body.shift(1)) & (body.shift(1) > body.shift(2))
pattern  = down_3 & bigger          # Boolean Series – your "three-red-bodies" trigger

rsi = vbt.RSI.run(price, 14).rsi
atr = vbt.ATR.run(df['high'], df['low'], price, 14).atr
chg1 = price.pct_change()
chg2 = chg1.shift(1)
chg3 = chg1.shift(2)

# Load the model
model_path = 'v2.joblib'
model = joblib.load(model_path)

# Apply IFT - Fixed to use normalized RSI properly
normalized_rsi = 0.1 * (rsi - 50)
ift_rsi = (np.exp(2 * normalized_rsi) - 1) / (np.exp(2 * normalized_rsi) + 1)

# Rebuild features
X = pd.concat([rsi, atr, chg1, chg2, chg3, ift_rsi], axis=1).dropna()
X.columns = ['rsi', 'atr', 'chg1', 'chg2', 'chg3', 'ift_rsi']

proba = model.predict_proba(X)[:, 1]
signal = pd.Series((proba > 0.3).astype(int), index=X.index)

# Align pattern with the feature matrix X to ensure same length/indices
pattern_aligned = pattern.reindex_like(X).fillna(False)

entries = (pattern_aligned & signal.astype(bool)).fillna(False)
exits   = entries.shift(1).fillna(False)   # flat after one bar, or design your own exit

# Align price data with the same index as entries/exits
price_aligned = price.reindex_like(X)

pf = vbt.Portfolio.from_signals(price_aligned, entries, exits, init_cash=100_000, direction='short_only')
print(pf.stats())
pf.trades.to_csv('trades.csv')
pf.plot().show()