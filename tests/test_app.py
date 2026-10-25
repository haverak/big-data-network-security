"""Exercise the actual local interface with the full prepared study data."""
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from PIL import Image
from streamlit.testing.v1 import AppTest

from analysis.query import apply_filters, compute_kpis, load_data
from app.photo import validate_photo

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app/main.py"


def start():
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    return at


def select_page(at, name):
    at.radio(key="section").set_value(name).run()
    assert not at.exception
    return at


def set_filter(at, key, values):
    at.checkbox(key=key + "_all").set_value(False).run()
    assert not at.exception
    at.multiselect(key=key).set_value(values).run()
    assert not at.exception
    return at


def metric(at, label):
    return next(item.value for item in at.metric if item.label == label)


def int_display(value):
    return f"{int(value):,}".replace(",", " ")


def test_all_six_sections_and_nine_actual_plotly_charts():
    at = start()
    assert metric(at, "Профилей трафика") == int_display(len(load_data()))
    for name in ["Данные", "Подготовка", "Аналитика", "Выводы", "Об авторе", "Главная"]:
        select_page(at, name)
        if name == "Аналитика":
            assert len(at.get("plotly_chart")) == 9
            assert len(at.selectbox(key="chart_group").options) == 4
        if name == "Об авторе":
            body = "\n".join(item.value for item in at.markdown)
            assert "Место для фотографии автора" in body
            assert "ДЕМОНСТРАЦИЯ" in body
            assert "Демонстрационный макет банковской карты" in body
            assert "НЕ ДЛЯ ПЛАТЕЖЕЙ" in body


def test_no_streamlit_magic_documentation_leaks_in_any_section():
    at = start()
    for name in ["Главная", "Данные", "Подготовка", "Аналитика", "Выводы", "Об авторе"]:
        select_page(at, name)
        assert len(at.get("doc_string")) == 0, name
        shown = "\n".join(str(item.value) for kind in [at.markdown, at.text, at.code] for item in kind)
        assert "DeltaGenerator" not in shown, name


def test_each_filter_matches_full_backend_query():
    df = load_data()
    options = {
        "protocols": ("tcp", {"protocols": ["tcp"]}),
        "classes": ("Атака", {"labels": ["Атака"]}),
        "families": (str(df["attack_family"].value_counts().index[0]), None),
        "services": (str(df["service"].value_counts().index[0]), None),
    }
    for key, (value, kwargs) in options.items():
        kwargs = kwargs or {key: [value]}
        at = select_page(start(), "Данные")
        set_filter(at, key, [value])
        expected = compute_kpis(apply_filters(df, **kwargs))
        assert metric(at, "Профилей трафика") == int_display(expected["rows"])
        assert metric(at, "Атак") == int_display(expected["attacks"])
        assert metric(at, "Нормальных") == int_display(expected["normal"])


def test_empty_selection_has_no_charts_or_traceback():
    at = select_page(start(), "Аналитика")
    set_filter(at, "protocols", [])
    assert metric(at, "Профилей трафика") == "0"
    assert len(at.get("plotly_chart")) == 0
    assert any("нет записей" in item.value for item in at.warning)


def test_real_group_filter_changes_displayed_charts():
    at = select_page(start(), "Аналитика")
    at.selectbox(key="chart_group").set_value("Состав трафика").run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 3


def test_export_matches_entire_filtered_selection():
    df = load_data()
    service = str(df["service"].value_counts().index[-1])
    expected = apply_filters(df, services=[service])
    at = select_page(start(), "Данные")
    set_filter(at, "services", [service])
    at.button(key="prepare_export").click().run()
    assert not at.exception
    exported = pd.read_csv(BytesIO(at.session_state["csv_export"]))
    assert len(exported) == len(expected)
    assert list(exported.columns) == list(expected.columns)
    assert set(exported["row_id"]) == set(expected["row_id"])
    # Changing the real selection discards the previously generated CSV.
    at.multiselect(key="services").set_value([str(df["service"].value_counts().index[-2])]).run()
    assert "csv_export" not in at.session_state


def test_missing_prepared_file_gives_actionable_error(monkeypatch, tmp_path):
    import analysis.query as query
    st.cache_resource.clear()
    with monkeypatch.context() as patch:
        patch.setattr(query, "PROCESSED", tmp_path / "absent")
        at = start()
        assert any("отсутствуют" in item.value for item in at.error)
        assert at.button[0].label == "Подготовить из исходного CSV"
        assert not at.exception
    st.cache_resource.clear()


def test_optional_photo_validation_accepts_real_png_and_rejects_invalid_bytes():
    buffer = BytesIO()
    Image.new("RGB", (3, 3), "#c5b490").save(buffer, format="PNG")
    assert validate_photo(buffer.getvalue()) == buffer.getvalue()
    with pytest.raises(ValueError, match="исправным изображением"):
        validate_photo(b"this is not an image")
    with pytest.raises(ValueError):
        validate_photo(b"\x89PNG\r\n\x1a\ntruncated")
