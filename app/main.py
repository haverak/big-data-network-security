"""Local Russian-language dashboard for the audited KDD99 assignment."""
from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.pipeline import prepare
from analysis.query import apply_filters, compute_kpis, load_data, load_quality, load_summary
from analysis.analytics import build_charts
from app.photo import validate_photo

SOURCE_URL = "https://www.kaggle.com/datasets/toobajamal/kdd99-dataset"
SECTIONS = ["Главная", "Данные", "Подготовка", "Аналитика", "Выводы", "Об авторе"]
GROUP_DESCRIPTIONS = {
    "Состав трафика": "Какие метки, типы атак и протоколы преобладают среди выбранных уникальных профилей? Три графика рассматривают один состав набора с разных сторон; их частоты следует сопоставлять с учётом удаления повторов.",
    "Характеристики соединений": "Как различаются длительность и объём данных у нормальных и атакующих профилей? Распределения дополняют средние показатели; логарифмическое представление раскрывает длинные хвосты без удаления экстремальных значений.",
    "Связи и статистические хвосты": "Какие признаки меняются совместно и где сосредоточены необычные профили? Корреляции, службы, ошибки и выбросы помогают уточнить наблюдения о составе трафика, но не устанавливают причину атаки.",
}

st.set_page_config(page_title="Сетевой трафик · Бондаренко", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
st.markdown(f"<style>{(ROOT / 'app/styles.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def integer(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def decimal(value, digits=1) -> str:
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def heading(eyebrow: str, title: str, text: str) -> None:
    st.markdown(f'<div class="hero"><div class="eyebrow">{html.escape(eyebrow)}</div><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></div>', unsafe_allow_html=True)


@st.cache_resource(show_spinner="Чтение подготовленного набора…")
def dataset_bundle():
    # Shared frames are read-only in this UI; transformations happen in the pipeline.
    return load_data(), load_quality(), load_summary()


def show_metrics(kpis: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Профилей трафика", integer(kpis["rows"]))
    cols[1].metric("Атак", integer(kpis["attacks"]))
    share = float(kpis["attack_share"])
    cols[2].metric("Доля атак", decimal(share * 100) + " %")
    cols[3].metric("Нормальных", integer(kpis["normal"]))


def filter_widget(label: str, all_label: str, values: list, key: str):
    all_values = st.sidebar.checkbox(all_label, value=True, key=key + "_all")
    chosen = st.sidebar.multiselect(label, values, default=[], disabled=all_values, key=key, placeholder="Выберите значения")
    return None if all_values else chosen


st.sidebar.markdown("### ТРАФИК / KDD99")
st.sidebar.caption("Индивидуальная работа № 2")
page = st.sidebar.radio("Раздел", SECTIONS, key="section", label_visibility="collapsed")
st.sidebar.divider()

try:
    data, quality, summary = dataset_bundle()
except (FileNotFoundError, OSError, ValueError) as exc:
    heading("Системы больших данных", "Подготовим данные", "Для анализа нужен локальный подготовленный набор. Исходный файл сохраняется без изменений.")
    st.error("Подготовленные данные отсутствуют или недоступны.")
    st.caption(str(exc))
    if st.button("Подготовить из исходного CSV", type="primary"):
        try:
            with st.spinner("Проверка и подготовка набора…"):
                prepare()
            dataset_bundle.clear()
            st.rerun()
        except (FileNotFoundError, OSError, ValueError) as prep_error:
            st.error("Не удалось подготовить данные. Проверьте исходный CSV в data/raw и повторите запуск.")
            st.caption(str(prep_error))
    st.stop()

st.sidebar.markdown("#### Фильтры набора")
st.sidebar.caption("Фильтры действуют в данных, аналитике и выводах. Снимите «Все», чтобы выбрать значения. Пустой выбор даёт пустую выборку.")
protocols = filter_widget("Протоколы", "Все протоколы", sorted(data["protocol_type"].dropna().unique().tolist()), "protocols")
classes = filter_widget("Классы трафика", "Все классы", sorted(data["traffic_class"].dropna().unique().tolist()), "classes")
families = filter_widget("Семейства", "Все семейства", sorted(data["attack_family"].dropna().unique().tolist()), "families")
services = filter_widget("Службы", "Все службы", sorted(data["service"].dropna().unique().tolist()), "services")

# The backend names its class filter labels; its actual field is traffic_class.
filtered = apply_filters(data, protocols=protocols, labels=classes, families=families, services=services)
kpis = compute_kpis(filtered)
full_kpis = compute_kpis(data)
st.sidebar.divider()
st.sidebar.caption(f"В выборке: {integer(len(filtered))} из {integer(len(data))} профилей")
st.sidebar.caption("Бондаренко К. В. · ИСТZS-3401\nРГЭУ (РИНХ) · 2026")

if page == "Главная":
    heading("Системы больших данных / № 2", "Что скрывает сетевой трафик", "Исследование признаков нормальных и атакующих соединений в KDD Cup 1999: от проверки исходного CSV до сравнения протоколов, служб и аномальных значений.")
    st.markdown('<span class="badge">Kaggle · реальные записи набора</span><span class="badge">41 исходный признак</span><span class="badge">Локальная обработка</span>', unsafe_allow_html=True)
    st.subheader("Подготовленный набор целиком")
    show_metrics(full_kpis)
    st.caption("Эти показатели описывают уникальные профили после удаления повторов, а не частоту реальных сетевых событий. Текущий выбор фильтров показан в боковой панели.")
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="quiet-card"><h3>От исходника к результату</h3><p>Проверяем типы, пропуски, повторы и допустимость значений. Сохраняем физические величины и отдельные нормализованные признаки. Подробности — в разделе «Подготовка».</p></div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="quiet-card"><h3>Девять ракурсов анализа</h3><p>Распределения классов, протоколов и служб, размеры и длительность соединений, ошибки и связи признаков. Каждый график сопровождается описанием и выводом по текущей выборке.</p></div>', unsafe_allow_html=True)
    st.subheader("Как читать исследование")
    st.write("Выберите раздел в боковой панели. В «Данных» можно проверить записи и выгрузить выборку. В «Аналитике» фильтры пересчитывают графики и показатели. «Выводы» объясняют результат и ограничения.")
    st.info("Источник сформирован контролируемой имитацией сети DARPA 1998 и её разметкой для KDD Cup 1999. Набор не характеризует частоту атак в современных сетях и не содержит календарного ряда для анализа тенденций по годам.")
    st.link_button("Источник на Kaggle ↗", SOURCE_URL)

elif page == "Данные":
    heading("Источник и структура", "Данные, которые можно проверить", "Одна строка подготовленного набора — уникальный профиль признаков сетевого соединения с меткой. После удаления точных повторов частоты показывают состав профилей, а не количество реальных событий.")
    show_metrics(kpis)
    st.link_button("KDD99 Dataset · Kaggle ↗", SOURCE_URL)
    st.caption("Исходник: data/raw/kddcup99_csv.csv. Подготовленный набор содержит производные поля; исходные 41 признак и метка сохранены для проверки.")
    with st.expander("Схема подготовленного набора", expanded=False):
        schema = pd.DataFrame({"Поле": data.columns, "Тип": [str(x) for x in data.dtypes]})
        st.dataframe(schema, hide_index=True, width="stretch")
    st.subheader("Просмотр текущей выборки")
    st.caption("Для быстрого просмотра показаны первые 500 строк текущей выборки. Все показатели и CSV относятся ко всей выборке.")
    st.dataframe(filtered.head(500), hide_index=True, width="stretch", height=420)
    if filtered.empty:
        st.warning("По выбранным фильтрам записей нет. Включите «Все» или выберите другие значения.")
    else:
        signature = hashlib.sha256(json.dumps([protocols, classes, families, services], ensure_ascii=False).encode()).hexdigest()
        if st.session_state.get("csv_signature") != signature:
            st.session_state.pop("csv_export", None)
        if st.button("Подготовить CSV выборки", key="prepare_export"):
            with st.spinner("Формирование CSV…"):
                st.session_state["csv_export"] = filtered.to_csv(index=False).encode("utf-8-sig")
                st.session_state["csv_signature"] = signature
        if "csv_export" in st.session_state:
            st.download_button("Скачать CSV выборки", st.session_state["csv_export"], file_name="kdd99_filtered.csv", mime="text/csv", type="primary", key="download_csv")
    st.subheader("Происхождение и границы применимости")
    st.write("Kaggle-публикация используется как источник файла; KDD Cup 1999 сформирован из контролируемой имитации сети DARPA 1998. Интерпретировать классы следует в рамках этой исторической учебной выборки. Совпадающие признаки не доказывают, что две реальные сессии были одним событием.")

elif page == "Подготовка":
    heading("Воспроизводимый конвейер", "Сначала качество, затем анализ", "Исходный CSV остаётся неизменным. Все решения об очистке и преобразовании фиксируются в журнале качества и могут быть повторены локально.")
    st.subheader("Этапы обработки")
    st.markdown("1. Чтение CSV и проверка схемы 41 признак + метка.\n2. Проверка типов, пропусков, повторов и допустимости значений.\n3. Очистка с фиксацией причин и количества затронутых записей.\n4. Создание производных величин и отдельных нормализованных признаков.\n5. Сохранение подготовленного Parquet и сводных показателей.")
    st.info("Экстремальный объём или длительность соединения могут описывать атаку. Выбросы отмечаются для анализа и не удаляются автоматически только из-за экстремального значения.")
    st.subheader("Баланс записей")
    records = quality.get("records", {})
    cols = st.columns(4)
    for col, key, label in zip(cols, ["source", "invalid_removed", "duplicates_removed", "prepared"], ["Строк в исходнике", "Недопустимых удалено", "Повторов удалено", "Уникальных профилей"]):
        value = records.get(key)
        col.metric(label, integer(value) if value is not None else "Не указано")
    st.caption("После удаления точных повторов единица анализа — уникальный профиль признаков с меткой; частоты не следует трактовать как частоту сетевых событий.")
    st.subheader("Решения конвейера")
    transformations = quality.get("transformations", [])
    if transformations:
        steps = pd.DataFrame(transformations).rename(columns={"step": "Шаг", "affected": "Затронуто", "unit": "Единица", "reason": "Обоснование"})
        st.dataframe(steps, hide_index=True, width="stretch")
    st.subheader("Классы до и после очистки")
    raw_classes = quality.get("raw_classes", {})
    prepared_classes = quality.get("prepared_classes", {})
    if isinstance(raw_classes, dict) and isinstance(prepared_classes, dict):
        class_table = pd.DataFrame({"Исходные строки": pd.Series(raw_classes), "Подготовленные профили": pd.Series(prepared_classes)}).fillna(0).astype("int64")
        class_table.index.name = "Класс"
        st.dataframe(class_table.reset_index(), hide_index=True, width="stretch")
    if quality.get("raw_unchanged") is True:
        st.success("Исходный файл не изменён.")
    else:
        st.warning("Сверьте контрольную сумму исходника в журнале качества.")
    with st.expander("Полный журнал качества и параметры преобразований"):
        st.json(quality, expanded=2)
    st.subheader("Что означает нормализация")
    st.write("Для выбранных числовых признаков создаются отдельные масштабированные столбцы. Исходные длительности, байты и доли остаются доступны в своих единицах. Параметры преобразования и ограничения указаны в журнале подготовки.")
    st.caption("Повторную подготовку можно выполнить командой, указанной в README. Она не требует изменения исходного файла.")

elif page == "Аналитика":
    heading("Девять графиков / одна выборка", "Сравнивайте, проверяйте, уточняйте", "Показатели и выводы ниже пересчитываются по фильтрам в боковой панели. Агрегированные расчёты используют всю выборку; примечание у графика раскрывает ограничение отображения, если оно применялось.")
    show_metrics(kpis)
    if filtered.empty:
        st.warning("По выбранным фильтрам нет записей. Измените фильтры, чтобы построить графики.")
    else:
        charts = build_charts(filtered, quality)
        groups = list(dict.fromkeys(chart["group"] for chart in charts))
        chosen_group = st.selectbox("Группа графиков", ["Все группы"] + groups, key="chart_group")
        active_group = None
        for number, chart in enumerate(charts, 1):
            if chosen_group != "Все группы" and chart["group"] != chosen_group:
                continue
            if active_group != chart["group"]:
                if active_group is not None:
                    st.divider()
                st.subheader(chart["group"])
                st.write(GROUP_DESCRIPTIONS.get(chart["group"], "Графики группы рассматривают взаимосвязанные аспекты текущей выборки."))
                active_group = chart["group"]
            st.markdown(f"#### {chart['title']}")
            st.write(chart["description"])
            fig = chart["figure"]
            fig.update_layout(paper_bgcolor="#121310", plot_bgcolor="#191B16", font_color="#DDE0D4")
            fig.update_xaxes(gridcolor="#34382D")
            fig.update_yaxes(gridcolor="#34382D")
            st.plotly_chart(fig, width="stretch", key=f"chart_{chart['id']}", config={"displaylogo": False, "scrollZoom": False})
            st.markdown("**Вывод.** " + str(chart["conclusion"]))
            if chart.get("note"):
                st.caption(chart["note"])

elif page == "Выводы":
    heading("Интерпретация результатов", "Что показывает выбранный трафик", "Здесь собраны проверяемые наблюдения о текущей выборке и ограничения, которые важны при обсуждении результатов.")
    show_metrics(kpis)
    if filtered.empty:
        st.warning("Выборка пуста. Выводы по данным появятся после изменения фильтров.")
    else:
        st.write(f"В текущей выборке {integer(kpis['rows'])} уникальных профилей; {integer(kpis['attacks'])} имеют метку атаки. Их доля составляет {decimal(float(kpis['attack_share']) * 100)} %. Это доля размеченных записей подготовленного набора после удаления повторов, а не оценка частоты реальных событий или риска для произвольной сети.")
        st.write(f"Медианная длительность соединения — {decimal(kpis['median_duration'])} с. Сумма байтов уникальных профилей — {integer(kpis['total_bytes'])} байт. Это сумма признаков после удаления повторов, а не объём реально наблюдавшейся сети. Профилей с отмеченным выбросом: {integer(kpis['outliers'])}.")
        top_protocol = filtered["protocol_type"].value_counts().index[0]
        top_service = filtered["service"].value_counts().index[0]
        st.write(f"Наиболее частый протокол в выборке — {top_protocol}, наиболее частая служба — {top_service}. Сравнение с распределением классов в аналитике позволяет увидеть, какие сочетания признаков связаны с разметкой атак.")
    st.subheader("Ограничения исследования")
    st.markdown("- Исторический учебный трафик не отражает структуру современных сетей.\n- Разметка набора является исходным основанием сравнения; приложение не обучает детектор атак.\n- Корреляция признаков не устанавливает причинную связь.\n- Повторы и дисбаланс классов влияют на распределения; решение о повторах раскрыто в журнале качества.\n- Временные тенденции по календарным датам не оцениваются: такого ряда в выбранных данных нет.\n- Отмеченные выбросы требуют содержательной интерпретации и сами по себе не доказывают атаку.")
    with st.expander("Сохранённая сводка полного набора"):
        st.json(summary, expanded=1)

else:
    heading("Об авторе и работе", "Бондаренко Константин Вячеславович", "Индивидуальная работа № 2 по дисциплине «Системы больших данных». Преподаватель — Щербаков.")
    left, right = st.columns([1, 2])
    with left:
        uploaded = st.file_uploader("Фотография автора — необязательно", type=["png", "jpg", "jpeg"], key="author_photo", help="Выбранное изображение используется локально для этой страницы. В комплекте нет вымышленной фотографии автора.")
        if uploaded is not None:
            try:
                photo = validate_photo(uploaded.getvalue())
                st.image(photo, caption="Фотография, выбранная пользователем", width="stretch")
            except ValueError as photo_error:
                st.error(str(photo_error))
        else:
            st.markdown('<div class="profile-placeholder">Место для фотографии автора<br>Добавьте своё изображение при необходимости</div>', unsafe_allow_html=True)
    with right:
        st.write("**Группа:** ИСТZS-3401 · 4 курс")
        st.write("**Университет:** РГЭУ (РИНХ)")
        st.write("**Год:** 2026")
        st.write("**Тема:** анализ сетевого трафика и информационной безопасности")
        st.write("**Инструменты:** Python, Streamlit, Pandas, NumPy, Plotly и Parquet / PyArrow.")
    st.subheader("Демонстрационный элемент задания")
    st.markdown('<div class="demo-card"><strong>ДЕМОНСТРАЦИЯ · НЕ ДЛЯ ПЛАТЕЖЕЙ</strong><span>Демонстрационный макет банковской карты</span><p>Учебный визуальный элемент задания. Номер карты, CVV, срок действия и платёжные реквизиты отсутствуют. Макет не выполняет платежей.</p></div>', unsafe_allow_html=True)
    st.subheader("Как воспроизвести результат")
    st.write("Запустите setup_windows.cmd для установки изолированного окружения, затем start_app.cmd. Подготовка данных, автоматические проверки и состав файлов описаны в README. Приложение работает локально на компьютере.")
    st.link_button("Открыть страницу источника ↗", SOURCE_URL)

st.markdown('<div class="footer-note">Системы больших данных · Индивидуальная работа № 2 · Бондаренко К. В. · ИСТZS-3401 · 2026</div>', unsafe_allow_html=True)
