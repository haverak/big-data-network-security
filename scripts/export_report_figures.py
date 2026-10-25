"""Export the app's full-data Plotly figures for the academic report."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from analysis.analytics import build_charts
from analysis.query import load_data,load_quality


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def series_sha(figure_json: str) -> str:
    data=json.loads(figure_json)['data']
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only',type=int,nargs='+',choices=range(1,10),help='Re-export selected figure numbers; retain verified others')
    parser.add_argument('--manifest-only',action='store_true',help='Verify all unchanged series/PNGs and refresh input/code hashes')
    args=parser.parse_args()
    if args.only and args.manifest_only:parser.error('--only and --manifest-only cannot be combined')
    edge=Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    if 'BROWSER_PATH' not in os.environ and edge.exists():os.environ['BROWSER_PATH']=str(edge)
    dest=ROOT/'reports/figures';dest.mkdir(parents=True,exist_ok=True)
    data=load_data();quality=load_quality()
    input_paths=[ROOT/'data/raw/kddcup99_csv.csv',ROOT/'data/processed/connections.parquet',ROOT/'data/processed/quality.json',ROOT/'data/processed/summary.json']
    inputs={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in input_paths}
    code_paths=(sorted((ROOT/'analysis').glob('*.py'))+sorted((ROOT/'app').glob('*.py'))+
        sorted((ROOT/'scripts').glob('*.py'))+sorted((ROOT/'tests').glob('*.py'))+
        [ROOT/'app/styles.css',ROOT/'.streamlit/config.toml',ROOT/'requirements.txt',ROOT/'requirements-lock.txt'])
    code_inputs={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in code_paths}
    entries=[]
    previous={}
    if args.only or args.manifest_only:
        previous={entry['number']:entry for entry in json.loads((dest/'manifest.json').read_text(encoding='utf-8'))['figures']}
    for index,chart in enumerate(build_charts(data,quality),1):
        figure=chart['figure']
        original=figure.to_json()
        original_series=series_sha(original)
        if args.manifest_only or (args.only and index not in args.only):
            assert previous[index]['series_sha256']==original_series,f'Unselected chart {index} changed; export it explicitly'
            assert sha(ROOT/previous[index]['png'])==previous[index]['png_sha256']
            entries.append(previous[index]|{k:chart[k] for k in ['id','group','title','description','conclusion','note']})
            continue
        app_path=dest/f'chart_{index:02d}_app.json';app_path.write_text(original,encoding='utf-8')
        figure.update_layout(template='plotly_white',width=1200,height=675,
            paper_bgcolor='white',plot_bgcolor='white',
            font={'family':'Arial','size':26,'color':'#202020'},
            title={'font':{'family':'Arial','size':32,'color':'#202020'},'x':.03,'y':.975,'xanchor':'left'},
            margin={'l':150,'r':75,'t':130,'b':120},
            legend={'font':{'size':26,'color':'#202020'},'orientation':'h','x':0,'y':1.05,'yanchor':'bottom','bgcolor':'rgba(255,255,255,.9)'})
        figure.update_xaxes(gridcolor='#D8DDD5',zerolinecolor='#8D9487',linecolor='#697061',tickfont={'size':24,'color':'#202020'},title_font={'size':26,'color':'#202020'},automargin=True)
        figure.update_yaxes(gridcolor='#D8DDD5',zerolinecolor='#8D9487',linecolor='#697061',tickfont={'size':24,'color':'#202020'},title_font={'size':26,'color':'#202020'},automargin=True)
        for annotation in figure.layout.annotations:
            annotation.font.update(color='#202020',size=28)
        if index==2:figure.update_layout(margin={'l':230,'r':60,'t':110,'b':90})
        if index==4:figure.update_yaxes(range=[0,102])
        if index==6:
            figure.update_layout(height=900,margin={'l':270,'r':110,'t':115,'b':245})
            figure.update_xaxes(tickangle=-40)
        if index==7:figure.update_layout(margin={'l':155,'r':65,'t':130,'b':105})
        if index==8:
            figure.update_layout(margin={'l':180,'r':200,'t':125,'b':100},
                polar={'bgcolor':'white','radialaxis':{'range':[0,1],'gridcolor':'#CBD2C5','linecolor':'#697061','tickfont':{'size':24,'color':'#202020'}},'angularaxis':{'gridcolor':'#CBD2C5','linecolor':'#697061','tickfont':{'size':24,'color':'#202020'}}})
        if index==9:
            figure.update_layout(margin={'l':150,'r':65,'t':130,'b':140})
            names=list(figure.data[0].x)
            figure.update_xaxes(tickangle=0,tickmode='array',tickvals=names,
                ticktext=[name.replace('Соединения к ','Соединения<br>к ') for name in names])
        rendered_json=figure.to_json()
        assert series_sha(rendered_json)==original_series, f'Series changed for chart {index}'
        json_path=dest/f'chart_{index:02d}.json';json_path.write_text(rendered_json,encoding='utf-8')
        png_path=dest/f'chart_{index:02d}.png'
        figure.write_image(png_path,width=1200,height=figure.layout.height,scale=1)
        entries.append({k:chart[k] for k in ['id','group','title','description','conclusion','note']}|{
            'number':index,'png':str(png_path.relative_to(ROOT)).replace('\\','/'),'figure_json':str(json_path.relative_to(ROOT)).replace('\\','/'),
            'app_figure_json':str(app_path.relative_to(ROOT)).replace('\\','/'),
            'width':1200,'height':int(figure.layout.height),'png_sha256':sha(png_path),'figure_json_sha256':sha(json_path),'app_figure_json_sha256':sha(app_path),
            'series_sha256':original_series,'series_unchanged':True,'profile_rows':len(data),'sampling':False})
        print(f'Exported {index:02d}: {chart["title"]}',flush=True)
    after={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in input_paths}
    assert after==inputs,'Source data changed while exporting figures'
    for entry in entries:
        entry['analytics_source_sha256']=code_inputs['analysis/analytics.py']
        entry['input_set_sha256']=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    manifest={'kind':'Plotly figure exports, not application screenshots','renderer':'Kaleido with installed Chromium-based browser','browser':os.environ.get('BROWSER_PATH'),'inputs_sha256':inputs,'source_code_sha256':code_inputs,'source_unchanged':True,'rows':len(data),'figures':entries}
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('All nine exports preserved original trace series and source files.',flush=True)


if __name__=='__main__':main()
