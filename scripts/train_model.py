#!/usr/bin/env python3
"""
🧠 Entrenar el modelo, validarlo sin trampas y exportarlo a ONNX solo si es rentable.

- Target: ¿el precio dentro de HORIZON_S segundos supera la entrada + comisiones?
- Validación walk-forward: siempre se entrena con el pasado y se prueba con el futuro,
  purgando las filas cuyo target se solapa con el periodo de test (evita la fuga de
  datos que daba el 91% falso del notebook).
- Solo se despliega si en walk-forward las señales dan retorno neto positivo.

Ejecutar desde ~/1TRADING: python scripts/train_model.py [--days 30] [--force]
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd
from onnx import save
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

from features import BASE_FEATURES, MIN_DAYS_FOR_TIME_FEATURES, TIME_FEATURES, add_features
import os

from dotenv import load_dotenv

load_dotenv()

MODEL_PATH = Path("models/solana_model_v1.onnx")
METADATA_PATH = Path("models/model_metadata.json")

HORIZON_S = 300             # 5 minutos
FEE_ROUND_TRIP = 0.0009     # 0.045% taker de entrada + 0.045% de salida en Hyperliquid
THRESHOLD = 0.60
N_FOLDS = 5
MIN_SIGNALS = 30            # mínimo de señales en walk-forward para fiarse del resultado


async def load_trades(days: int) -> pd.DataFrame:
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        database='solana_trading',
        user='solana_user',
        password=os.getenv('DB_PASSWORD')
    )
    rows = await conn.fetch(
        "SELECT timestamp, price, size, side FROM solana_trades "
        "WHERE timestamp > NOW() - make_interval(days => $1) ORDER BY timestamp, id",
        days
    )
    await conn.close()
    df = pd.DataFrame(rows, columns=['time', 'price', 'size', 'side'])
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df[['price', 'size']] = df[['price', 'size']].astype(float)
    return df


def add_target(df: pd.DataFrame) -> pd.DataFrame:
    """Precio del último trade a t + HORIZON_S y retorno neto de comisiones."""
    future = df[['time', 'price']].rename(columns={'price': 'future_price'})
    lookup = pd.DataFrame({'time': df['time'] + pd.Timedelta(seconds=HORIZON_S)})
    matched = pd.merge_asof(lookup, future, on='time', direction='backward')
    df = df.copy()
    df['future_price'] = matched['future_price'].to_numpy()
    # Sin datos suficientes hacia delante: no hay target
    df.loc[df['time'] + pd.Timedelta(seconds=HORIZON_S) > df['time'].iloc[-1], 'future_price'] = np.nan
    df['net_return'] = df['future_price'] / df['price'] - 1 - FEE_ROUND_TRIP
    df['target'] = (df['net_return'] > 0).astype(int)
    return df


def make_model() -> RandomForestClassifier:
    # Hojas grandes: trades consecutivos se parecen mucho, así evitamos memorizar ruido
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=50,
        class_weight='balanced_subsample',
        random_state=42,
        n_jobs=-1,
    )


def walk_forward(df: pd.DataFrame, feature_cols: list) -> dict:
    """Entrenar con bloques pasados y evaluar en el siguiente bloque, purgando solapes."""
    edges = pd.date_range(df['time'].iloc[0], df['time'].iloc[-1], periods=N_FOLDS + 2)
    horizon = pd.Timedelta(seconds=HORIZON_S)
    signals = []
    aucs = []

    for k in range(1, N_FOLDS + 1):
        test_start, test_end = edges[k], edges[k + 1]
        train = df[df['time'] + horizon < test_start]
        test = df[(df['time'] >= test_start) & (df['time'] < test_end)]
        if len(train) < 500 or len(test) < 100 or train['target'].nunique() < 2:
            continue

        model = make_model().fit(train[feature_cols].astype('float32'), train['target'])
        prob = model.predict_proba(test[feature_cols].astype('float32'))[:, 1]
        if test['target'].nunique() == 2:
            aucs.append(roc_auc_score(test['target'], prob))

        taken = test[prob >= THRESHOLD]
        signals.append(taken[['time', 'net_return', 'target']])
        print(f"   Fold {k}: train {len(train):>6} | test {len(test):>6} | "
              f"señales {len(taken):>5} | retorno neto medio "
              f"{taken['net_return'].mean() if len(taken) else float('nan'):+.4%}")

    sig = pd.concat(signals) if signals else pd.DataFrame(columns=['time', 'net_return', 'target'])
    # Señales muy seguidas son casi la misma operación: contar 1 por ventana de HORIZON_S
    if len(sig):
        sig = sig.sort_values('time')
        keep, last = [], None
        for t in sig['time']:
            keep.append(last is None or t >= last + horizon)
            if keep[-1]:
                last = t
        trades = sig[keep]
    else:
        trades = sig

    return {
        'auc': float(np.mean(aucs)) if aucs else None,
        'base_rate': float(df['target'].mean()),
        'n_trades': int(len(trades)),
        'win_rate': float(trades['target'].mean()) if len(trades) else None,
        'mean_net_return': float(trades['net_return'].mean()) if len(trades) else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--force', action='store_true',
                        help='Exportar aunque la validación no sea rentable')
    args = parser.parse_args()

    print("📡 Descargando trades desde PostgreSQL...")
    trades = asyncio.run(load_trades(args.days))
    if trades.empty:
        sys.exit("❌ No hay trades en la base de datos")
    span_days = (trades['time'].iloc[-1] - trades['time'].iloc[0]).total_seconds() / 86400
    print(f"✅ {len(trades)} trades en {span_days:.2f} días "
          f"({trades['time'].iloc[0]:%Y-%m-%d %H:%M} → {trades['time'].iloc[-1]:%Y-%m-%d %H:%M} UTC)")

    feature_cols = list(BASE_FEATURES)
    if span_days >= MIN_DAYS_FOR_TIME_FEATURES:
        feature_cols += TIME_FEATURES
    else:
        print(f"ℹ️  Features de hora desactivadas (hacen falta {MIN_DAYS_FOR_TIME_FEATURES} días de datos)")

    df = add_target(add_features(trades))
    df = df.dropna(subset=feature_cols + ['future_price']).reset_index(drop=True)
    print(f"🔧 {len(df)} filas | features: {feature_cols}")
    print(f"🎯 Target: subida > comisiones ({FEE_ROUND_TRIP:.2%}) en {HORIZON_S}s | "
          f"% positivos: {df['target'].mean():.1%}")

    print(f"\n📊 Validación walk-forward (umbral {THRESHOLD:.0%}):")
    metrics = walk_forward(df, feature_cols)
    print(f"\n   AUC medio: {metrics['auc'] if metrics['auc'] is None else round(metrics['auc'], 3)} (0.5 = azar)")
    print(f"   Operaciones simuladas: {metrics['n_trades']}")
    if metrics['n_trades']:
        print(f"   Aciertos: {metrics['win_rate']:.1%} (base: {metrics['base_rate']:.1%})")
        print(f"   Retorno neto medio por operación: {metrics['mean_net_return']:+.4%}")

    profitable = (metrics['n_trades'] >= MIN_SIGNALS and metrics['mean_net_return'] > 0)
    if not profitable and not args.force:
        print(f"\n⛔ Modelo NO desplegado: hace falta retorno neto > 0 con al menos "
              f"{MIN_SIGNALS} operaciones en walk-forward. Sigue acumulando datos.")
        sys.exit(1)

    # Modelo final con todos los datos
    model = make_model().fit(df[feature_cols].astype('float32'), df['target'])

    initial_type = [('float_input', FloatTensorType([None, len(feature_cols)]))]
    onnx_model = convert_sklearn(model, initial_types=initial_type)
    for key, value in {'features': ','.join(feature_cols), 'horizon_s': str(HORIZON_S)}.items():
        meta = onnx_model.metadata_props.add()
        meta.key, meta.value = key, value

    if MODEL_PATH.exists():
        backup = MODEL_PATH.with_name(f"{MODEL_PATH.stem}_{datetime.now():%Y%m%d_%H%M%S}.onnx.bak")
        shutil.copy2(MODEL_PATH, backup)
        print(f"\n💾 Modelo anterior guardado en {backup}")

    tmp = MODEL_PATH.with_suffix('.onnx.tmp')
    with open(tmp, 'wb') as f:
        save(onnx_model, f)
    tmp.replace(MODEL_PATH)  # atómico: el motor nunca lee un archivo a medias

    METADATA_PATH.write_text(json.dumps({
        'created_at': datetime.now(timezone.utc).isoformat(),
        'features': feature_cols,
        'horizon_s': HORIZON_S,
        'fee_round_trip': FEE_ROUND_TRIP,
        'threshold': THRESHOLD,
        'n_rows': len(df),
        'data_days': round(span_days, 2),
        'walk_forward': metrics,
        'forced': bool(args.force and not profitable),
    }, indent=2))
    print(f"✅ Modelo exportado a {MODEL_PATH} ({'FORZADO, no rentable en validación' if not profitable else 'validado'})")


if __name__ == '__main__':
    main()
