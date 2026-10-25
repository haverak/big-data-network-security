"""Подготовка без изменения raw: python -m analysis.pipeline --force.

Идентичные профили удаляются по всем 42 исходным полям. При отсутствии
времени/ID нельзя считать их доказанными повторными захватами одних событий.
Исходные и уникальные распределения сохраняются отдельно.
"""
from __future__ import annotations
import argparse, hashlib, json, os, time
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from .config import RAW, PROCESSED, DATASET_URL, ALIASES, CATEGORICAL, FEATURES, FAMILIES

VERSION = '1.0'
def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def json_save(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)

def counts(series):return {str(k):int(v) for k,v in series.value_counts(dropna=False).items()}

def clean_frame(source:pd.DataFrame):
    """Чистая функция для фактических данных и изолированных тестовых примеров."""
    df=source.rename(columns=ALIASES).copy()
    required=set(CATEGORICAL+FEATURES)
    missing=sorted(required-set(df.columns))
    if missing:raise ValueError('В CSV отсутствуют обязательные столбцы: '+', '.join(missing))
    source_columns=list(df.columns)
    numeric=[x for x in source_columns if x not in CATEGORICAL]
    raw_missing={x:int(df[x].isna().sum()) for x in source_columns}
    changed={}
    for col in CATEGORICAL:
        before=df[col].astype('string')
        after=before.str.strip()
        if col in ('protocol_type','label'):after=after.str.lower()
        if col=='label':after=after.str.rstrip('.')
        changed[col]=int((before!=after).fillna(False).sum())
        df[col]=after.replace('',pd.NA)
    invalid=pd.Series(False,index=df.index)
    invalid_by_column={}
    for col in numeric:
        values=pd.to_numeric(df[col],errors='coerce')
        bad=values.isna()|~np.isfinite(values)|values.lt(0)
        if col.endswith('_rate'):bad|=values.gt(1)
        invalid_by_column[col]=int(bad.sum());invalid|=bad;df[col]=values
    invalid|=df[CATEGORICAL].isna().any(axis=1)
    invalid_rows=int(invalid.sum())
    valid=df.loc[~invalid].copy()
    raw_labels=counts(valid['label'])
    raw_classes={'Нормальный':int(valid['label'].eq('normal').sum()),'Атака':int(valid['label'].ne('normal').sum())}
    duplicated=valid.duplicated(subset=source_columns,keep='first')
    duplicates=int(duplicated.sum())
    valid=valid.loc[~duplicated].copy()
    valid['row_id']=(valid.index.to_numpy()+1).astype('int64')
    valid['traffic_class']=np.where(valid['label'].eq('normal'),'Нормальный','Атака')
    valid['attack_family']=valid['label'].map(FAMILIES).fillna('Другие атаки')
    valid['total_bytes']=valid['src_bytes'].astype('int64')+valid['dst_bytes'].astype('int64')
    normalization={};outliers={};outlier_any=np.zeros(len(valid),dtype=bool)
    for col in FEATURES:
        x=valid[col].astype('float64')
        logged=np.log1p(x);minimum=float(logged.min()) if len(x) else 0.;maximum=float(logged.max()) if len(x) else 0.
        valid[col+'_scaled']=(logged-minimum)/(maximum-minimum) if maximum>minimum else 0.
        normalization[col]={'method':'log1p_then_minmax','raw_unit_preserved':True,'log_min':minimum,'log_max':maximum,
            'constant':maximum==minimum,'fit_scope':'all prepared unique profiles'}
        q1=float(x.quantile(.25)) if len(x) else 0.;q3=float(x.quantile(.75)) if len(x) else 0.;iqr=q3-q1
        threshold=q3+1.5*iqr if iqr>0 else (float(x.quantile(.995)) if len(x) else 0.)
        flag=x.gt(threshold).to_numpy();valid['outlier_'+col]=flag;outlier_any|=flag
        outliers[col]={'q1':q1,'q3':q3,'iqr':iqr,'upper_threshold':threshold,
            'method':'Q3 + 1.5 IQR' if iqr>0 else 'Q99.5 because IQR = 0','flagged':int(flag.sum()),'removed':0}
    valid['outlier_any']=outlier_any
    constants=[c for c in source_columns if valid[c].nunique(dropna=False)<=1]
    warnings=[]
    if 'su_attempted' in valid:
        unusual=valid['su_attempted'].loc[~valid['su_attempted'].isin([0,1])]
        if len(unusual):warnings.append({'column':'su_attempted','count':len(unusual),'values':counts(unusual),
            'decision':'Сохранено без перекодирования; неоднозначные значения не используются в основных графиках.'})
    for col in numeric:
        if not col.endswith('_rate') and np.equal(valid[col],np.floor(valid[col])).all():
            valid[col]=pd.to_numeric(valid[col],downcast='unsigned')
    for col in CATEGORICAL+['traffic_class','attack_family']:valid[col]=valid[col].astype('category')
    quality={'schema_version':VERSION,'records':{'source':len(source),'invalid_removed':invalid_rows,
        'duplicates_removed':duplicates,'prepared':len(valid)},'columns':{'original':list(source.columns),'canonical':source_columns,
        'renamed':{a:b for a,b in ALIASES.items() if a in source},'prepared':list(valid.columns)},
        'missing_before':raw_missing,'invalid_by_column':invalid_by_column,'strings_standardized':changed,
        'raw_labels':raw_labels,'raw_classes':raw_classes,'prepared_labels':counts(valid['label']),
        'prepared_classes':counts(valid['traffic_class']),'constant_columns':constants,'warnings':warnings,
        'normalization':normalization,'outliers':outliers,
        'transformations':[
            {'step':'Канонические названия полей','affected':len([a for a in ALIASES if a in source]),'unit':'столбцов','reason':'Восемь l-алиасов зеркала приведены к официальным названиям UCI; порядок и значения сохранены.'},
            {'step':'Нормализация строк','affected':sum(changed.values()),'unit':'значений','reason':'Пробелы, регистр протокола/метки и завершающая точка метки не несут аналитического смысла.'},
            {'step':'Исключение некорректных записей','affected':invalid_rows,'unit':'записей','reason':'Пропуски, нечисловые, бесконечные, отрицательные значения и доли вне [0,1] нельзя безопасно заменить.'},
            {'step':'Удаление точных дубликатов','affected':duplicates,'unit':'записей','reason':'Уникальность проверяется по всем 42 исходным полям, включая label. Это профили, а не доказанные уникальные события во времени.'},
            {'step':'Числовая нормализация','affected':len(FEATURES),'unit':'добавленных признаков','reason':'log1p уменьшает асимметрию; MinMax приводит признаки к [0,1]. Исходные значения и единицы сохранены.'},
            {'step':'Разметка статистических хвостов','affected':int(outlier_any.sum()),'unit':'профилей','reason':'Верхний порог Q3+1,5 IQR, при IQR=0 — Q99,5. Ничего не удаляется; флаг не является детектором атак.'}],
        'memory_bytes':int(valid.memory_usage(deep=True).sum()),
        'dtypes':{c:str(t) for c,t in valid.dtypes.items()}}
    return valid.reset_index(drop=True),quality

def summarize(df,quality):
    total=len(df);attack=int(df['traffic_class'].eq('Атака').sum())
    return {'rows':total,'attacks':attack,'normal':total-attack,'attack_share':attack/total if total else 0.,
        'median_duration':float(df['duration'].median()) if total else 0.,'total_bytes':int(df['total_bytes'].sum()),
        'outliers':int(df['outlier_any'].sum()),'labels':counts(df['label']),
        'protocols':counts(df['protocol_type']),'families':counts(df['attack_family']),
        'source_rows':quality['records']['source'],'duplicates_removed':quality['records']['duplicates_removed'],
        'quantiles':{c:{str(q):float(df[c].quantile(q)) for q in (0,.25,.5,.75,.95,.99,1)} for c in FEATURES} if total else {}}

def prepare(force=False,raw_path=None,output_dir=None):
    raw=Path(raw_path or RAW);out=Path(output_dir or PROCESSED)
    if not raw.exists():raise FileNotFoundError(f'Нет исходного CSV: {raw}. Выполните setup_windows.cmd или python -m analysis.download.')
    before=file_sha(raw);code_hash=file_sha(__file__);config_hash=file_sha(Path(__file__).with_name('config.py'))
    if not force and (out/'quality.json').exists() and (out/'connections.parquet').exists():
        previous=json.loads((out/'quality.json').read_text(encoding='utf-8'))
        if previous.get('source_sha256')==before and previous.get('pipeline_sha256')==code_hash and previous.get('config_sha256')==config_hash:return previous
    started=time.perf_counter()
    frame=pd.read_csv(raw,encoding='utf-8-sig',skip_blank_lines=True,on_bad_lines='error',low_memory=False)
    if len(frame.columns)!=42:raise ValueError(f'Ожидалось 42 поля, получено {len(frame.columns)}.')
    with raw.open('r',encoding='utf-8-sig',newline=None) as stream:blank=sum(not line.strip() for line in stream)
    prepared,quality=clean_frame(frame)
    quality.update({'dataset_url':DATASET_URL,'source_file':raw.name,'source_sha256':before,'pipeline_sha256':code_hash,'config_sha256':config_hash,
        'dependencies':{'pandas':pd.__version__,'numpy':np.__version__},
        'blank_lines_skipped':blank,'encoding':'UTF-8 strict; source unchanged','created_utc':datetime.now(timezone.utc).isoformat()})
    out.mkdir(parents=True,exist_ok=True)
    temporary=out/'connections.tmp.parquet';prepared.to_parquet(temporary,index=False,compression='zstd');os.replace(temporary,out/'connections.parquet')
    summary=summarize(prepared,quality)
    quality['processing_seconds']=time.perf_counter()-started
    assert file_sha(raw)==before,'Исходный CSV неожиданно изменён.'
    quality['raw_unchanged']=True
    json_save(out/'quality.json',quality);json_save(out/'summary.json',summary)
    json_save(out/'normalization.json',quality['normalization'])
    for name,col in [('attack_counts','label'),('protocol_counts','protocol_type'),('family_counts','attack_family')]:
        prepared[col].value_counts().rename_axis(col).reset_index(name='profiles').to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
    return quality

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--force',action='store_true');parser.add_argument('--raw',type=Path);args=parser.parse_args()
    q=prepare(args.force,args.raw)
    print(json.dumps({'status':'ok','records':q['records'],'raw_unchanged':q['raw_unchanged'],'seconds':q['processing_seconds']},ensure_ascii=False,indent=2))
