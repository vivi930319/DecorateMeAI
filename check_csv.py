# 先看 CSV 實際長什麼樣子
import pandas as pd
from pathlib import Path

ATTR_FILE = Path("celeba_raw/list_attr_celeba.csv")
df = pd.read_csv(ATTR_FILE)
print("欄位名稱：")
print(df.columns.tolist())
print("\n前兩行：")
print(df.head(2))
