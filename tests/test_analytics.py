"""Check chart inputs and totals independently, rather than snapshotting Plotly output."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.analytics import build_charts
from analysis.pipeline import clean_frame
from analysis.query import apply_filters, compute_kpis


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
FEATURES = ['duration', 'src_bytes', 'dst_bytes', 'count', 'srv_count']
CORRELATION_FIELDS = FEATURES + ['serror_rate', 'rerror_rate', 'same_srv_rate', 'dst_host_count']


@pytest.fixture
def prepared_sample():
    # Explicit small observations. These are never written into project data/.
    fields = {
        'duration': [0, 1, 4, 20, 100, 1000, 8, 0],
        'src_bytes': [0, 10, 30, 50, 100, 10000, 200, 7],
        'dst_bytes': [0, 20, 5, 40, 300, 2, 50, 9],
        'count': [1, 2, 3, 4, 100, 20, 7, 8],
        'srv_count': [1, 2, 4, 3, 8, 50, 5, 7],
        'serror_rate': [0, .1, .4, .2, .9, .8, .3, .5],
        'rerror_rate': [.2, .1, 0, .3, .1, .5, .8, .6],
        'same_srv_rate': [1, .9, .8, .7, .2, .4, .6, .3],
        'dst_host_count': [1, 2, 3, 4, 5, 6, 7, 8],
        'protocol_type': ['tcp', 'tcp', 'udp', 'icmp', 'tcp', 'udp', 'icmp', 'tcp'],
        'service': ['http', 'http', 'domain_u', 'eco_i', 'ftp', 'domain_u', 'eco_i', 'ftp'],
        'label': ['normal', 'neptune', 'normal', 'smurf', 'normal', 'neptune', 'satan', 'normal'],
        'flag': ['SF', 'S0', 'SF', 'SF', 'REJ', 'S0', 'SF', 'SF'],
    }
    source = pd.DataFrame({column: fields.get(column, [0] * 8) for column in RAW_COLUMNS})
    prepared, quality = clean_frame(source)
    assert len(prepared) == 8
    return prepared, quality


def chart_map(df, quality):
    return {item['id']: item for item in build_charts(df, quality)}


def test_filter_none_means_all_but_empty_selection_means_none(prepared_sample):
    df, _ = prepared_sample
    pd.testing.assert_frame_equal(apply_filters(df), df)
    for keyword in ['protocols', 'labels', 'families', 'services']:
        assert apply_filters(df, **{keyword: []}).empty
    all_values = dict(protocols=df['protocol_type'].unique().tolist(),
                      labels=df['traffic_class'].unique().tolist(),
                      families=df['attack_family'].unique().tolist(),
                      services=df['service'].unique().tolist())
    assert apply_filters(df, **all_values)['row_id'].tolist() == list(range(1, 9))


def test_cross_filters_and_unknown_values(prepared_sample):
    df, _ = prepared_sample
    chosen = apply_filters(df, protocols=['tcp'], labels=['Атака'], families=['DoS'], services=['http'])
    assert chosen['row_id'].tolist() == [2]
    assert apply_filters(df, protocols=['unknown-protocol']).empty
    assert apply_filters(df, protocols=['udp'], services=['http']).empty


def test_kpis_are_independent_of_displayed_group_statistics(prepared_sample):
    df, _ = prepared_sample
    assert compute_kpis(df) == {
        'rows': 8, 'attacks': 4, 'normal': 4, 'attack_share': .5,
        'median_duration': 6.0, 'total_bytes': 10823, 'outliers': 2,
    }
    chosen = apply_filters(df, protocols=['tcp'], services=['http'])
    assert compute_kpis(chosen) == {
        'rows': 2, 'attacks': 1, 'normal': 1, 'attack_share': .5,
        'median_duration': .5, 'total_bytes': 30, 'outliers': 0,
    }


def test_nine_chart_specs_are_complete_and_do_not_sample(prepared_sample, monkeypatch):
    df, quality = prepared_sample
    def sampling_is_not_allowed(*args, **kwargs):
        raise AssertionError('The nine charts must use all filtered profiles.')
    monkeypatch.setattr(pd.DataFrame, 'sample', sampling_is_not_allowed)
    monkeypatch.setattr(pd.Series, 'sample', sampling_is_not_allowed)
    specs = build_charts(df, quality)
    assert [s['id'] for s in specs] == [
        '01_class', '02_attacks', '03_protocols', '04_duration', '05_bytes',
        '06_correlation', '07_services', '08_normalized', '09_outliers',
    ]
    assert len({s['group'] for s in specs}) == 3
    for item in specs:
        for field in ['title', 'description', 'conclusion', 'group']:
            assert isinstance(item[field], str) and item[field].strip()
        assert 'nan%' not in item['conclusion'].lower()
        assert item['figure'].layout.title.text == item['title']


def test_full_class_attack_and_protocol_counts(prepared_sample):
    df, quality = prepared_sample
    charts = chart_map(df, quality)
    pie = charts['01_class']['figure'].data[0]
    assert dict(zip(pie.labels, pie.values)) == {'Нормальный': 4, 'Атака': 4}
    attacks = charts['02_attacks']['figure'].data[0]
    assert dict(zip(attacks.y, attacks.x)) == {'neptune': 2, 'smurf': 1, 'satan': 1}
    assert 'normal' not in attacks.y
    protocol = charts['03_protocols']['figure']
    observed = {(str(x), trace.name): int(y)
                for trace in protocol.data for x, y in zip(trace.x, trace.y)}
    assert observed == {
        ('tcp', 'Нормальный'): 3, ('tcp', 'Атака'): 1,
        ('udp', 'Нормальный'): 1, ('udp', 'Атака'): 1,
        ('icmp', 'Нормальный'): 0, ('icmp', 'Атака'): 2,
    }
    assert sum(observed.values()) == 8


def test_bytes_histogram_counts_every_observation_once(prepared_sample):
    df, quality = prepared_sample
    fig = chart_map(df, quality)['05_bytes']['figure']
    assert sum(int(np.sum(trace.y)) for trace in fig.data) == len(df)
    for trace in fig.data:
        assert len(trace.y) == 40
        assert np.all(np.asarray(trace.y) >= 0)
        expected = int(df['traffic_class'].eq(trace.name).sum())
        assert int(np.sum(trace.y)) == expected
        assert np.asarray(trace.customdata).shape == (40, 2)


def test_service_percentages_have_per_service_denominators(prepared_sample):
    df, quality = prepared_sample
    fig = chart_map(df, quality)['07_services']['figure']
    totals, counts = {}, {}
    for trace in fig.data:
        for service, percentage, count in zip(trace.y, trace.x, trace.customdata):
            totals[service] = totals.get(service, 0.0) + float(percentage)
            counts[service] = counts.get(service, 0) + int(count)
    assert totals and all(abs(v - 100) < 1e-10 for v in totals.values())
    assert counts == {'http': 2, 'ftp': 2, 'domain_u': 2, 'eco_i': 2}
    assert sum(counts.values()) == len(df)


def average_tie_ranks(values):
    ordered = sorted(set(values))
    rank, result = 1, {}
    for value in ordered:
        count = values.count(value)
        result[value] = (rank + rank + count - 1) / 2
        rank += count
    return [result[value] for value in values]


def test_spearman_heatmap_matches_independent_rank_correlation(prepared_sample):
    df, quality = prepared_sample
    z = np.asarray(chart_map(df, quality)['06_correlation']['figure'].data[0].z, dtype=float)
    ranks = np.array([average_tie_ranks(df[c].tolist()) for c in CORRELATION_FIELDS])
    expected = np.corrcoef(ranks)
    assert z.shape == (9, 9)
    np.testing.assert_allclose(z, expected, atol=1e-12, rtol=1e-12)
    np.testing.assert_allclose(np.diag(z), np.ones(9), atol=1e-12)
    np.testing.assert_allclose(z, z.T, atol=1e-12)
    assert np.nanmax(np.abs(z)) <= 1 + 1e-12


def test_normalized_radar_uses_global_scale_and_means_of_all_filtered_rows(prepared_sample):
    df, quality = prepared_sample
    chosen = apply_filters(df, protocols=['tcp'])
    fig = chart_map(chosen, quality)['08_normalized']['figure']
    for trace in fig.data:
        selected = chosen.loc[chosen['traffic_class'].eq(trace.name)]
        values = np.asarray(trace.r, dtype=float)
        expected = [float(selected[c + '_scaled'].mean()) for c in FEATURES]
        np.testing.assert_allclose(values, expected + [expected[0]], atol=1e-12)
        assert ((values >= 0) & (values <= 1)).all()
    for column in FEATURES:
        np.testing.assert_array_equal(chosen[column + '_scaled'],
                                      df.loc[chosen.index, column + '_scaled'])


def test_duration_cdf_and_outlier_rates_use_all_selected_rows(prepared_sample):
    df, quality = prepared_sample
    charts = chart_map(df, quality)
    for trace in charts['04_duration']['figure'].data:
        values = df.loc[df['traffic_class'].eq(trace.name), 'duration'].to_numpy(dtype=float)
        durations = sorted(set(values))
        expected = [100 * sum(v <= threshold for v in values) / len(values) for threshold in durations]
        np.testing.assert_allclose(trace.customdata, durations)
        np.testing.assert_allclose(trace.x, np.log10(1 + np.array(durations)))
        np.testing.assert_allclose(trace.y, expected)
        assert trace.y[-1] == 100
        assert all(a <= b for a,b in zip(trace.y,trace.y[1:]))
    for trace in charts['09_outliers']['figure'].data:
        selected = df.loc[df['traffic_class'].eq(trace.name)]
        expected = [100 * int(selected['outlier_' + c].sum()) / len(selected) for c in FEATURES]
        np.testing.assert_allclose(trace.y, expected, atol=1e-12)


def test_normal_only_slice_has_no_attack_bars_or_nan_conclusion(prepared_sample):
    df, quality = prepared_sample
    chosen = apply_filters(df, labels=['Нормальный'])
    charts = chart_map(chosen, quality)
    assert len(charts) == 9
    attacks = charts['02_attacks']
    assert len(attacks['figure'].data) == 0
    assert attacks['figure'].layout.annotations
    assert 'nan' not in attacks['conclusion'].lower()
    services = charts['07_services']['figure']
    for trace in services.data:
        expected = 100 if trace.name == 'Нормальный' else 0
        np.testing.assert_allclose(trace.x, np.full(len(trace.x), expected))


def test_empty_slice_and_single_observation_are_handled(prepared_sample):
    df, quality = prepared_sample
    empty = apply_filters(df, protocols=[])
    assert build_charts(empty, quality) == []
    assert compute_kpis(empty) == {
        'rows': 0, 'attacks': 0, 'normal': 0, 'attack_share': 0.0,
        'median_duration': 0.0, 'total_bytes': 0, 'outliers': 0,
    }
    charts = chart_map(df.iloc[:1], quality)
    assert len(charts) == 9
    z = np.asarray(charts['06_correlation']['figure'].data[0].z, dtype=float)
    assert np.isnan(z).all(), 'Insufficient observations must remain undefined, not false zero correlations.'
