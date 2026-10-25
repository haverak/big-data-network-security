from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/kddcup99_csv.csv'
PROCESSED = ROOT / 'data/processed'
DATASET_URL = 'https://www.kaggle.com/datasets/toobajamal/kdd99-dataset'
DOWNLOAD_URL = 'https://www.kaggle.com/api/v1/datasets/download/toobajamal/kdd99-dataset'
ALIASES = {x: x[1:] for x in ['lnum_compromised','lroot_shell','lsu_attempted','lnum_root',
    'lnum_file_creations','lnum_shells','lnum_access_files','lnum_outbound_cmds']}
CATEGORICAL = ['protocol_type','service','flag','label']
FEATURES = ['duration','src_bytes','dst_bytes','count','srv_count']
FEATURE_NAMES = {'duration':'Длительность','src_bytes':'Отправлено','dst_bytes':'Получено',
    'count':'Соединения к хосту','srv_count':'Соединения к сервису'}
UNITS = {'duration':'с','src_bytes':'байт','dst_bytes':'байт','count':'соединений за 2 с','srv_count':'соединений за 2 с'}
FAMILIES = {
    'normal':'Нормальный', 'back':'DoS','land':'DoS','neptune':'DoS','pod':'DoS','smurf':'DoS','teardrop':'DoS',
    'ipsweep':'Probe','nmap':'Probe','portsweep':'Probe','satan':'Probe',
    'ftp_write':'R2L','guess_passwd':'R2L','imap':'R2L','multihop':'R2L','phf':'R2L','spy':'R2L','warezclient':'R2L','warezmaster':'R2L',
    'buffer_overflow':'U2R','loadmodule':'U2R','perl':'U2R','rootkit':'U2R',
}
