"""Independent quality checks; all generated fixtures live in pytest temp folders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.config import RAW
from analysis.pipeline import clean_frame, prepare


RAW_COLUMNS = (
    'duration protocol_type service flag src_bytes dst_bytes land wrong_fragment urgent hot '
    'num_failed_logins logged_in lnum_compromised lroot_shell lsu_attempted lnum_root '
    'lnum_file_creations lnum_shells lnum_access_files lnum_outbound_cmds is_host_login '
    'is_guest_login count srv_count serror_rate srv_serror_rate rerror_rate srv_rerror_rate '
    'same_srv_rate diff_srv_rate srv_diff_host_rate dst_host_count dst_host_srv_count '
    'dst_host_same_srv_rate dst_host_diff_srv_rate dst_host_same_src_port_rate '
    'dst_host_srv_diff_host_rate dst_host_serror_rate dst_host_srv_serror_rate '
    'dst_host_rerror_rate dst_host_srv_rerror_rate label'
).split()
ALIASES_EXPECTED = {
    'lnum_compromised': 'num_compromised', 'lroot_shell': 'root_shell',
    'lsu_attempted': 'su_attempted', 'lnum_root': 'num_root',
    'lnum_file_creations': 'num_file_creations', 'lnum_shells': 'num_shells',
    'lnum_access_files': 'num_access_files', 'lnum_outbound_cmds': 'num_outbound_cmds',
}
NORMALIZED_FEATURES = ['duration', 'src_bytes', 'dst_bytes', 'count', 'srv_count']


def raw_row(**changes):
    row = {column: 0 for column in RAW_COLUMNS}
    row.update(protocol_type='tcp', service='http', flag='SF', label='normal',
               duration=2, src_bytes=10, dst_bytes=20, count=3, srv_count=5)
    row.update(changes)
    return row


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def actual_dataset(tmp_path_factory):
    assert RAW.is_file(), 'Bundled source CSV is required for the actual-data audit.'
    before = digest(RAW)
    source = pd.read_csv(RAW, encoding='utf-8-sig', low_memory=False)
    output = tmp_path_factory.mktemp('actual_prepared_independent')
    quality = prepare(force=True, raw_path=RAW, output_dir=output)
    prepared = pd.read_parquet(output / 'connections.parquet')
    assert digest(RAW) == before
    yield source, prepared, quality, output, before
    assert digest(RAW) == before, 'The raw file changed during tests.'


def test_actual_counts_and_raw_file_are_unchanged(actual_dataset):
    source, prepared, quality, output, before = actual_dataset
    assert source.shape == (494020, 42)
    independent_duplicates = int(source.duplicated(keep='first').sum())
    assert independent_duplicates == 348435
    assert len(prepared) == 145585
    assert quality['records'] == {
        'source': 494020, 'invalid_removed': 0,
        'duplicates_removed': 348435, 'prepared': 145585,
    }
    assert quality['raw_unchanged'] is True
    assert quality['source_sha256'] == before == digest(RAW)
    assert output.parent != RAW.parent


def test_actual_eight_aliases_and_source_values_are_preserved(actual_dataset):
    source, prepared, quality, _, _ = actual_dataset
    assert len(ALIASES_EXPECTED) == 8
    assert quality['columns']['renamed'] == ALIASES_EXPECTED
    assert not set(ALIASES_EXPECTED).intersection(prepared.columns)
    assert set(ALIASES_EXPECTED.values()).issubset(prepared.columns)
    # row_id identifies the retained original row, not a newly invented source ID.
    retained = source.iloc[prepared['row_id'].to_numpy(dtype=np.int64) - 1]
    for original in RAW_COLUMNS:
        canonical = ALIASES_EXPECTED.get(original, original)
        expected = retained[original].reset_index(drop=True)
        observed = prepared[canonical].reset_index(drop=True)
        if original in ['protocol_type', 'service', 'flag', 'label']:
            assert observed.astype(str).tolist() == expected.astype(str).tolist()
        else:
            np.testing.assert_array_equal(observed.to_numpy(), expected.to_numpy())


def test_actual_no_missing_nonfinite_or_out_of_range_rates(actual_dataset):
    _, prepared, quality, _, _ = actual_dataset
    assert not prepared.isna().any().any()
    numeric = prepared.select_dtypes(include=['number']).to_numpy(dtype=np.float64)
    assert np.isfinite(numeric).all()
    rate_columns = [c for c in prepared.columns if c.endswith('_rate')]
    assert rate_columns
    for column in rate_columns:
        assert prepared[column].between(0, 1, inclusive='both').all()
    assert sum(quality['missing_before'].values()) == 0
    assert sum(quality['invalid_by_column'].values()) == 0


def test_actual_extreme_values_and_unusual_su_attempted_are_retained(actual_dataset):
    source, prepared, quality, _, _ = actual_dataset
    numeric_source = [c for c in RAW_COLUMNS if c not in ['protocol_type', 'service', 'flag', 'label']]
    for column in numeric_source:
        canonical = ALIASES_EXPECTED.get(column, column)
        assert prepared[canonical].min() == source[column].min()
        assert prepared[canonical].max() == source[column].max()
    unusual_original = source.loc[source['lsu_attempted'].eq(2)].drop_duplicates()
    assert len(unusual_original) > 0
    assert int(prepared['su_attempted'].eq(2).sum()) == len(unusual_original)
    warning = next(w for w in quality['warnings'] if w['column'] == 'su_attempted')
    assert warning['count'] == len(unusual_original)
    assert warning['values']['2'] == len(unusual_original)
    assert all(details['removed'] == 0 for details in quality['outliers'].values())


def test_actual_normalization_is_independently_recomputed(actual_dataset):
    _, prepared, quality, _, _ = actual_dataset
    for column in NORMALIZED_FEATURES:
        values = prepared[column].to_numpy(dtype=np.float64)
        logged = np.log1p(values)
        spread = logged.max() - logged.min()
        expected = (logged - logged.min()) / spread if spread else np.zeros(len(values))
        observed = prepared[column + '_scaled'].to_numpy(dtype=np.float64)
        np.testing.assert_allclose(observed, expected, atol=1e-12, rtol=1e-12)
        assert np.isfinite(observed).all()
        assert ((observed >= 0) & (observed <= 1)).all()
        assert quality['normalization'][column]['fit_scope'] == 'all prepared unique profiles'


def test_small_42_field_fixture_deduplicates_all_fields_and_keeps_other_labels():
    baseline = raw_row()
    source = pd.DataFrame([
        baseline, dict(baseline), raw_row(hot=1),
        raw_row(label='neptune'), raw_row(duration=-1),
    ], columns=RAW_COLUMNS)
    before = source.copy(deep=True)
    result, quality = clean_frame(source)
    pd.testing.assert_frame_equal(source, before)
    assert source.shape == (5, 42)
    assert quality['records'] == {
        'source': 5, 'invalid_removed': 1, 'duplicates_removed': 1, 'prepared': 3,
    }
    assert result['label'].astype(str).tolist().count('normal') == 2
    assert set(result['label'].astype(str)) == {'normal', 'neptune'}
    assert set(result['hot'].tolist()) == {0, 1}
    assert result['row_id'].tolist() == [1, 3, 4]


@pytest.mark.parametrize('column,value', [
    ('duration', -1), ('src_bytes', float('inf')), ('dst_bytes', 'not-a-number'),
    ('serror_rate', 1.01), ('same_srv_rate', -0.01),
    ('label', '   '), ('protocol_type', None), ('srv_count', np.nan),
])
def test_invalid_fixture_rows_are_removed_with_explanation(column, value):
    source = pd.DataFrame([raw_row(), raw_row(**{column: value})], columns=RAW_COLUMNS)
    result, quality = clean_frame(source)
    assert len(result) == 1
    assert quality['records']['invalid_removed'] == 1
    assert quality['records']['duplicates_removed'] == 0


def test_string_cleanup_and_constant_feature_scale_zero():
    source = pd.DataFrame([
        raw_row(protocol_type=' TCP ', label=' NORMAL. ', service=' http ', flag=' SF '),
        raw_row(),
    ], columns=RAW_COLUMNS)
    result, quality = clean_frame(source)
    assert len(result) == 1
    assert quality['records']['duplicates_removed'] == 1
    assert result['label'].astype(str).tolist() == ['normal']
    assert result['protocol_type'].astype(str).tolist() == ['tcp']
    for column in NORMALIZED_FEATURES:
        assert result[column + '_scaled'].tolist() == [0.0]
        assert quality['normalization'][column]['constant'] is True
    assert sum(quality['strings_standardized'].values()) == 4


def test_header_only_42_column_csv_is_processed_without_nan(tmp_path):
    raw = tmp_path / 'empty.csv'
    pd.DataFrame(columns=RAW_COLUMNS).to_csv(raw, index=False)
    before = digest(raw)
    quality = prepare(force=True, raw_path=raw, output_dir=tmp_path / 'processed')
    assert quality['records'] == {
        'source': 0, 'invalid_removed': 0, 'duplicates_removed': 0, 'prepared': 0,
    }
    prepared = pd.read_parquet(tmp_path / 'processed' / 'connections.parquet')
    assert prepared.empty
    assert digest(raw) == before
    summary = json.loads((tmp_path / 'processed' / 'summary.json').read_text(encoding='utf-8'))
    assert summary['rows'] == 0 and summary['attack_share'] == 0
    assert summary['quantiles'] == {}


def test_missing_raw_csv_is_actionable_and_does_not_create_output(tmp_path):
    destination = tmp_path / 'not_created'
    with pytest.raises(FileNotFoundError, match='setup_windows.cmd'):
        prepare(force=True, raw_path=tmp_path / 'missing.csv', output_dir=destination)
    assert not destination.exists()


def test_wrong_number_of_source_fields_is_rejected(tmp_path):
    raw = tmp_path / 'wrong_schema.csv'
    pd.DataFrame([raw_row()], columns=RAW_COLUMNS[:-1]).to_csv(raw, index=False)
    with pytest.raises(ValueError, match='42'):
        prepare(force=True, raw_path=raw, output_dir=tmp_path / 'not_created')


def test_missing_required_column_is_reported():
    source = pd.DataFrame([raw_row()], columns=RAW_COLUMNS).drop(columns='duration')
    with pytest.raises(ValueError, match='duration'):
        clean_frame(source)
