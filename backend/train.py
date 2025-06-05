import vectorbt as vbt
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report, roc_auc_score
import joblib
import os

# Load data from local CSV
df = pd.read_csv('./data/TSLA_5m.csv', index_col=0, parse_dates=True)


# Extract price data
price = df['close']
open_ = df['open']
high = df['high']
low = df['low']


IFTIndicator = vbt.IndicatorFactory(
    input_names=['x'],
    output_names=['ift']
).from_custom_func(
    lambda x : pd.DataFrame((np.exp(2 * x) - 1) / (np.exp(2 * x) + 1))
)

body     = (price - open_).abs()
down_3   = (price < price.shift(1)) & (price.shift(1) < price.shift(2))
bigger   = (body > body.shift(1)) & (body.shift(1) > body.shift(2))
pattern  = down_3 & bigger          # Boolean Series – your "three-red-bodies" trigger

atr   = vbt.ATR.run(high, low, price, 14).atr
chg1  = price.pct_change()
chg2  = chg1.shift(1)
chg3  = chg1.shift(2)
rsi = vbt.RSI.run(price, 14).rsi
normalized_rsi = 0.1 * (rsi - 50)
ift_rsi = IFTIndicator.run(normalized_rsi).ift

X = pd.concat([rsi, atr, chg1, chg2, chg3, ift_rsi], axis=1).dropna()
X.columns = ['rsi', 'atr', 'chg1', 'chg2', 'chg3', 'ift_rsi']

fwd_ret = price.pct_change(5).shift(-2)
y       = (fwd_ret < -0.004).astype(int).reindex_like(X)

print(f"Total data points: {len(X)}")

print("Training new model...")   
# Calculate appropriate window size
train_size = int(0.7 * len(X))
train_idx = X.index[:train_size]
test_idx  = X.index[train_size:]

clf = GradientBoostingClassifier(max_depth=3, n_estimators=200)
clf.fit(X.loc[train_idx], y.loc[train_idx])

# Predict on test set
proba = clf.predict_proba(X.loc[test_idx])[:, 1]
preds = (proba > 0.3)

# Evaluate edge
print(classification_report(y.loc[test_idx], preds))
print("AUC:", roc_auc_score(y.loc[test_idx], proba))

model_path = 'trained_model.joblib'

# Check if a saved model exists
if os.path.exists(model_path):
    print("Loading existing model...")
    clf = joblib.load(model_path)
else: # Save the trained model
    print("Saving model...")
    try:
        joblib.dump(clf, model_path)
    except Exception as e:
        print(f"Error saving model: {e}")
   

