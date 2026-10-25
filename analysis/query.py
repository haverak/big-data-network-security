from pathlib import Path
import json
import pandas as pd
from .config import PROCESSED

def load_data():
    path=PROCESSED/'connections.parquet'
    if not path.exists():raise FileNotFoundError('Подготовленные данные отсутствуют. Выполните setup_windows.cmd или python -m analysis.pipeline.')
    return pd.read_parquet(path)
def load_quality():return json.loads((PROCESSED/'quality.json').read_text(encoding='utf-8'))
def load_summary():return json.loads((PROCESSED/'summary.json').read_text(encoding='utf-8'))

def apply_filters(df,protocols=None,labels=None,families=None,services=None):
    mask=pd.Series(True,index=df.index)
    for col,values in [('protocol_type',protocols),('traffic_class',labels),('attack_family',families),('service',services)]:
        if values is not None:mask&=df[col].isin(values)
    return df.loc[mask]

def compute_kpis(df):
    total=len(df);attacks=int(df['traffic_class'].eq('Атака').sum())
    return {'rows':total,'attacks':attacks,'normal':total-attacks,'attack_share':attacks/total if total else 0.,
        'median_duration':float(df['duration'].median()) if total else 0.,
        'total_bytes':int(df['total_bytes'].sum()) if total else 0,'outliers':int(df['outlier_any'].sum()) if total else 0}
