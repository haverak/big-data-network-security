"""Девять графиков из всех отфильтрованных профилей, без случайных выборок."""
from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .config import FEATURES,FEATURE_NAMES,UNITS

COLORS={'Нормальный':'#61b89b','Атака':'#e58c79'}
AMBER='#e3b76b'
def fmt(value):return f'{int(value):,}'.replace(',',' ')
def pct(value):return f'{100*value:.2f}%'.replace('.',',')
def base(fig,title,x=None,y=None,height=420):
    fig.update_layout(title={'text':title,'font':{'size':19}},template='plotly_dark',
        paper_bgcolor='#131a1e',plot_bgcolor='#131a1e',font={'family':'Arial','color':'#e9ecef'},
        margin={'l':65,'r':25,'t':70,'b':70},height=height,legend={'orientation':'h','y':1.12,'x':0},
        hoverlabel={'font':{'size':13}},colorway=[AMBER,COLORS['Нормальный'],COLORS['Атака']])
    if x:fig.update_xaxes(title=x,gridcolor='#2a343b')
    if y:fig.update_yaxes(title=y,gridcolor='#2a343b')
    return fig
def empty(title,message):
    fig=go.Figure();fig.add_annotation(text=message,x=.5,y=.5,xref='paper',yref='paper',showarrow=False)
    return base(fig,title)
def spec(id,group,title,description,conclusion,figure,note=''):
    return dict(id=id,group=group,title=title,description=description,conclusion=conclusion,figure=figure,note=note)

def build_charts(df,quality):
    if df.empty:return []
    result=[];n=len(df);classes=['Нормальный','Атака'];group='Состав трафика'
    class_counts={c:int(df['traffic_class'].eq(c).sum()) for c in classes}
    fig=go.Figure(go.Pie(labels=classes,values=[class_counts[c] for c in classes],hole=.62,
        marker={'colors':[COLORS[c] for c in classes]},textinfo='label+percent',
        hovertemplate='%{label}: %{value:,} профилей (%{percent})<extra></extra>',sort=False))
    fig.add_annotation(text=f'{fmt(n)}<br>профилей',x=.5,y=.5,showarrow=False,font={'size':18})
    title='01 · Нормальный трафик и атаки'
    result.append(spec('01_class',group,title,'Доля меток в уникальных профилях текущей выборки. Единица — профиль соединения.',
        f"Метка атаки есть у {fmt(class_counts['Атака'])} из {fmt(n)} профилей ({pct(class_counts['Атака']/n)}). Это доля в учебных данных, а не оценка риска реальной сети.",base(fig,title)))
    attacks=df.loc[df['label'].ne('normal'),'label'].value_counts()
    attacks=attacks.loc[attacks.gt(0)]
    title='02 · Частота типов атак'
    if len(attacks):
        shown=attacks.head(15).sort_values()
        fig=go.Figure(go.Bar(y=shown.index.astype(str),x=shown.to_numpy(),orientation='h',marker_color=COLORS['Атака'],hovertemplate='%{y}: %{x:,} профилей<extra></extra>'))
        conclusion=f"Чаще всего встречается {attacks.index[0]}: {fmt(attacks.iloc[0])} профилей, {pct(attacks.iloc[0]/attacks.sum())} всех атак в выбранном срезе."
        note=f'Показаны {len(shown)} из {len(attacks)} типов; статистика вычислена по всем {fmt(int(attacks.sum()))} атакующим профилям.'
    else:fig=empty(title,'В выборке нет профилей с меткой атаки');conclusion='В выбранном срезе присутствует только нормальный трафик.';note=''
    result.append(spec('02_attacks',group,title,'Число профилей каждого типа атаки; normal исключён только из этого графика.',conclusion,base(fig,title,'Профили, шт.','Тип атаки',490),note))
    cross=pd.crosstab(df['protocol_type'],df['traffic_class']).reindex(columns=classes,fill_value=0)
    fig=go.Figure()
    for c in classes:fig.add_bar(x=cross.index.astype(str),y=cross[c],name=c,marker_color=COLORS[c],hovertemplate='%{x}: %{y:,} профилей<extra>'+c+'</extra>')
    fig.update_layout(barmode='stack');title='03 · Сетевые протоколы и метки'
    largest=cross.sum(axis=1).sort_values(ascending=False)
    result.append(spec('03_protocols',group,title,'Полные счётчики TCP, UDP и ICMP с разделением по метке. Размер столбца — число профилей.',
        f'Самый частый протокол — {largest.index[0]}: {fmt(largest.iloc[0])} профилей ({pct(largest.iloc[0]/n)} выбранного среза).',base(fig,title,'Протокол','Профили, шт.')))
    group='Характеристики соединений';title='04 · Длительность по классу трафика';fig=go.Figure();medians={};zero_shares={}
    for c in classes:
        values=df.loc[df['traffic_class'].eq(c),'duration'].to_numpy(dtype=float)
        if not len(values):continue
        durations,frequencies=np.unique(values,return_counts=True)
        cumulative=100*np.cumsum(frequencies)/len(values)
        medians[c]=float(np.median(values));zero_shares[c]=float(np.mean(values==0))
        fig.add_trace(go.Scatter(name=c,x=np.log10(1+durations),y=cumulative,customdata=durations,
            mode='lines+markers',line={'color':COLORS[c],'shape':'hv'},marker={'size':3},
            hovertemplate='Не более %{customdata:g} с: %{y:.2f}% профилей класса<extra>'+c+'</extra>'))
    conclusion='; '.join(f'«{c}»: медиана {medians[c]:g} с, нулевое значение у {pct(zero_shares[c])}' for c in medians)+'. Ноль в секундном признаке не означает отсутствие пакетов.'
    fig.update_yaxes(range=[0,100])
    result.append(spec('04_duration',group,title,'Эмпирическая функция распределения: доля профилей класса с длительностью не более значения по оси X. Каждая точка учитывает все повторения этой длительности, без случайной выборки.',conclusion,
        base(fig,title,'log10(1 + длительность / 1 с)','Накопленная доля класса, %'), 'Нулевые квартили делают коробчатую диаграмму неинформативной, поэтому используется CDF. Сохранён весь диапазон длительности, включая экстремальные значения.'))
    title='05 · Объём переданных данных';fig=go.Figure();upper=float(np.log10(1+df['total_bytes'].max()))
    bins=np.linspace(0,upper if upper>0 else 1,41);centers=(bins[:-1]+bins[1:])/2
    for c in classes:
        values=df.loc[df['traffic_class'].eq(c),'total_bytes'].to_numpy(dtype=float)
        if not len(values):continue
        hist,_=np.histogram(np.log10(1+values),bins=bins);assert int(hist.sum())==len(values)
        fig.add_bar(x=centers,y=hist,name=c,marker_color=COLORS[c],opacity=.75,
            customdata=np.column_stack([np.maximum(0,10**bins[:-1]-1),np.maximum(0,10**bins[1:]-1)]),
            hovertemplate='%{customdata[0]:,.0f}–%{customdata[1]:,.0f} байт: %{y:,} профилей<extra>'+c+'</extra>')
    fig.update_layout(barmode='overlay')
    result.append(spec('05_bytes',group,title,'total_bytes = src_bytes + dst_bytes, в байтах. 40 интервалов на логарифмической оси; каждый профиль входит ровно в один интервал.',
        f"Медианный суммарный объём — {df['total_bytes'].median():,.0f} байт, максимум — {int(df['total_bytes'].max()):,} байт. Длинный хвост требует логарифмической шкалы.",
        base(fig,title,'log10(1 + объём / 1 байт)','Профили, шт.'),'Гистограмма использует все профили; случайная выборка не применяется.'))
    group='Связи и статистические хвосты';title='06 · Корреляции сетевых характеристик'
    fields=['duration','src_bytes','dst_bytes','count','srv_count','serror_rate','rerror_rate','same_srv_rate','dst_host_count']
    names=['Длительность, с','Отправлено, байт','Получено, байт','К хосту / 2 с','К сервису / 2 с','SYN-ошибки, доля','REJ-ошибки, доля','Тот же сервис, доля','Хост: соединения']
    corr=df[fields].corr(method='spearman',min_periods=3)
    fig=go.Figure(go.Heatmap(z=corr.to_numpy(),x=names,y=names,zmin=-1,zmax=1,
        colorscale=[[0,'#a55d3e'],[.5,'#263239'],[1,'#68bda4']],colorbar={'title':'ρ'},
        hovertemplate='%{x}<br>%{y}<br>ρ = %{z:.3f}<extra></extra>'))
    pairs=corr.where(np.triu(np.ones(corr.shape),k=1).astype(bool)).stack()
    if len(pairs):
        pair=pairs.abs().idxmax();conclusion=f'Наибольшая по модулю связь: {pair[0]} ↔ {pair[1]}, ρ = {pairs.loc[pair]:.3f}. Корреляция не доказывает причинность.'
    else:conclusion='Недостаточно непостоянных наблюдений для оценки корреляций; пустые клетки не заменяются нулями.'
    result.append(spec('06_correlation',group,title,'Ранговая корреляция Спирмена по всем профилям. Коэффициент безразмерный; постоянные признаки дают пустые клетки.',conclusion,base(fig,title,height=600)))
    title='07 · Метки трафика по сервисам'
    table=pd.crosstab(df['service'],df['traffic_class']).reindex(columns=classes,fill_value=0)
    order=table.sum(axis=1).nlargest(12).index;table=table.loc[order];totals=table.sum(axis=1);fig=go.Figure()
    for c in classes:
        fig.add_bar(y=table.index.astype(str),x=100*table[c]/totals,name=c,orientation='h',marker_color=COLORS[c],customdata=table[c].to_numpy(),
            hovertemplate='%{y}: %{x:.2f}% (%{customdata:,} профилей)<extra>'+c+'</extra>')
    fig.update_layout(barmode='stack');best=totals.idxmax()
    result.append(spec('07_services',group,title,'Соотношение меток внутри каждого сервиса. Показаны 12 наиболее частых сервисов текущей выборки; проценты имеют отдельный знаменатель для каждой строки.',
        f'Самый частый сервис — {best}: {fmt(totals.loc[best])} профилей; доля метки атаки в нём {pct(table.loc[best,"Атака"]/totals.loc[best])}.',
        base(fig,title,'Доля профилей сервиса, %','Сервис',500),'Фильтр класса меняет знаменатель: при единственном выбранном классе доля каждой строки равна 100%.'))
    title='08 · Нормализованные профили';fig=go.Figure();theta=[FEATURE_NAMES[c] for c in FEATURES]
    for c in classes:
        selected=df.loc[df['traffic_class'].eq(c)]
        if selected.empty:continue
        values=[float(selected[f+'_scaled'].mean()) for f in FEATURES]
        fig.add_trace(go.Scatterpolar(r=values+[values[0]],theta=theta+[theta[0]],fill='toself',name=c,line={'color':COLORS[c]},opacity=.8))
    fig.update_layout(polar={'bgcolor':'#131a1e','radialaxis':{'range':[0,1],'gridcolor':'#34414a'},'angularaxis':{'gridcolor':'#34414a'}})
    result.append(spec('08_normalized',group,title,'Средние пяти признаков после log1p и MinMax. Единица — безразмерная шкала [0,1]. Параметры преобразования рассчитаны на всём подготовленном наборе и при фильтрации не меняются.',
        'Различия линий описывают средние характеристики выбранных классов. Преобразование сохраняет порядок значений и исходные столбцы; радиальная площадь не является оценкой опасности.',base(fig,title,height=500),
        'Формула: (log1p(x) − min) / (max − min). Постоянный признак получает 0. Это обязательная числовая нормализация, а не удаление выбросов.'))
    title='09 · Частота статистических хвостов';fig=go.Figure()
    for c in classes:
        selected=df.loc[df['traffic_class'].eq(c)]
        if selected.empty:continue
        values=[100*selected['outlier_'+f].mean() for f in FEATURES]
        fig.add_bar(x=theta,y=values,name=c,marker_color=COLORS[c],hovertemplate='%{x}: %{y:.2f}%<extra>'+c+'</extra>')
    fig.update_layout(barmode='group');flagged=int(df['outlier_any'].sum())
    rules=quality.get('outliers',{})
    fallback=[FEATURE_NAMES[c] for c in FEATURES if rules.get(c,{}).get('iqr')==0]
    note='Пороги рассчитаны на всём подготовленном наборе. '+('При IQR=0 используется Q99,5: '+', '.join(fallback)+'.' if fallback else 'Для всех признаков используется Q3 + 1,5 IQR.')
    result.append(spec('09_outliers',group,title,'Доля профилей выше верхнего порога по каждому из пяти исходных признаков. Порог фиксирован до пользовательской фильтрации.',
        f'Хотя бы один порог превышен у {fmt(flagged)} профилей ({pct(flagged/n)} выбранного среза). Такие значения сохранены; статистический хвост не равнозначен сетевой атаке.',
        base(fig,title,'Характеристика','Доля профилей класса, %',470),note))
    assert len(result)==9
    return result
