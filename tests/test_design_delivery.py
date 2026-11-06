"""The unwired delivery is source-only, text-free and driven by workbook slots."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

import pytest
from PIL import Image,ImageDraw,ImageFont
from design import build_all,contracts,core,data

ROOT=Path(__file__).resolve().parents[1]
ITEMS=json.loads((ROOT/'design/catalog.json').read_text())['plates']
TOKENS=json.loads((ROOT/'kit/design-tokens.json').read_text())
INK=TOKENS['hours']['night']['plateInk']['paper']
DATA_ITEMS=[i for i in ITEMS if core.needs_data(i)]

@pytest.fixture(scope='module')
def compiled():
    return {item['key']+'-'+aspect:(item,*build_all.compile_plate(item,aspect,INK,2)) for item in ITEMS for aspect in ('16x9','9x16')}

def test_unique_concepts_and_published_kit_motion(compiled):
    assert len(ITEMS)==188 and len(compiled)==376 and len(DATA_ITEMS)==125
    assert len({i['key'] for i in ITEMS})==188
    assert sum('motion' in i for i in ITEMS)==120
    published={}
    for f in (ROOT/'kit').glob('*/manifest.json'):
        m=json.loads(f.read_text());table=m.get('plates',m.get('assets',{}))
        if isinstance(table,dict):published.update(table)
    assert set(compiled).isdisjoint(published)
    kit=json.loads((ROOT/'design/kit-motion.json').read_text())['plates']
    assert len(kit)==104
    moves={m['id'] for m in json.loads((ROOT/'kit/emit/motion.json').read_text())['moves']}
    for key,recipe in kit.items():
        assert key in published
        assert recipe['steps']
        for step in recipe['steps']:
            assert step['slot'] in published[key]['slots']
            assert step['cueSlot'] in published[key]['slots']
            if 'move' in step:assert step['move'] in moves

def test_common_manifest_and_text_free_artwork(compiled):
    chapter_types=set(json.loads((ROOT/'kit/roles.json').read_text())['chapterTypes'])
    for key,(item,entry,nodes) in compiled.items():
        assert re.fullmatch(r'[a-z0-9-]+/[a-z0-9-]+-(16x9|9x16)',key)
        assert not any(p in key for p in ('vol2','library'))
        assert entry['ground']=='paper' and entry['bakedText'] is False
        assert entry['exportScale']==2 and entry['delivered']==[v*2 for v in entry['canvas']]
        assert entry['playback']=='static' and entry['fps']==0 and entry['frameCount']==1
        assert isinstance(entry['slots'],dict) and entry['purpose'] and entry['caution']
        assert set(entry['chapterTypes'])<=chapter_types and set(entry['sectors'])<=set(build_all.SECTORS)
        assert not {'brand','file'}&entry['slots'].keys()
        for name,slot in entry['slots'].items():
            assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name)
            assert {'x','y','w','h','role','align','maxChars','authoredLines','fit','note'}<=slot.keys()
            if slot.get('region'):
                assert slot['renderer']
                continue
            role=entry['typeRoles'][slot['role']]
            assert role['font'] in ('Archivo Narrow','Courier Prime')
            assert role['colour'] in core.INK_NAMES and not role['colour'].startswith('#')
            assert len(entry['example'][name])<=slot['maxChars']
        assert all(n['tag'] in ('rect','circle','path') for n in nodes)
        assert all('opacity' not in n['attrs'] for n in nodes)
        assert not any('data-slot' in n['attrs'] for n in nodes)
        if core.needs_data(item):
            # Numeric body, ticks, legends and sample values are runtime data.
            assert len(nodes)==2  # paper canvas and footer rule, no sample chart
            region=entry['slots']['data-area']
            for name in region['inputSlots']:
                assert name in entry['slots'] and entry['slots'][name]['note'].startswith('Workbook:')
                assert isinstance(entry['example'][name],str)

def test_motion_is_slot_data_without_baked_timing(compiled):
    forbidden={'seconds','fps','frames','duration','frameCount','start','delay','opacity'}
    def inspect(value):
        if isinstance(value,dict):
            assert not forbidden&value.keys()
            for x in value.values():inspect(x)
        elif isinstance(value,list):
            for x in value:inspect(x)
    for _,entry,_ in compiled.values():
        if 'motion' not in entry:continue
        inspect(entry['motion'])
        for step in entry['motion']['steps']:
            assert step['slot'] in entry['slots'] and step['cueSlot'] in entry['slots']
            assert step.get('action') in ('appear','clip-in','draw-on','grow') or step.get('move')
    inspect(json.loads((ROOT/'design/kit-motion.json').read_text()))

@pytest.mark.parametrize('item',DATA_ITEMS,ids=lambda i:i['key'])
def test_every_data_drawing_is_pure_and_paintable(item,compiled):
    for aspect in ('16x9','9x16'):
        _,entry,_=compiled[item['key']+'-'+aspect];region=entry['slots']['data-area']
        values={k:entry['example'][k] for k in region['inputSlots']};snapshot=deepcopy((region,values,INK))
        with patch('builtins.open',side_effect=AssertionError('data renderer read a file')),patch.object(Path,'read_text',side_effect=AssertionError('data renderer read a file')),patch.object(subprocess,'run',side_effect=AssertionError('data renderer ran a subprocess')),patch.object(Image,'new',side_effect=AssertionError('data renderer created an image')),patch.object(ImageFont,'truetype',side_effect=AssertionError('data renderer loaded a font')):
            nodes=data.draw(region,values,INK);labels=data.labels(region,values,INK)
        assert (region,values,INK)==snapshot
        assert nodes and labels and all(n['tag'] in ('rect','circle','path') for n in nodes)
        for n in nodes:
            assert set(n)=={'tag','attrs'}
            core.finite(n['attrs'])
            for name in ('fill','stroke'):
                if name in n['attrs']:assert n['attrs'][name] in ('none',*INK.values())
        assert all(l['slot'] in entry['slots'] for l in labels)
        assert all(isinstance(l['text'],str) and len(l['box'])==4 for l in labels)

@pytest.mark.parametrize('value,unit,expected',[('$1.2bn','money_m',1200),('−12.5%','percent',-12.5),('($40m)','money_m',-40),('14x','multiple',14),('1,250.5','raw',1250.5)])
def test_script_number_units(value,unit,expected):assert data.number(value,unit)==expected

@pytest.mark.parametrize('value,unit',[(True,'raw'),('NaN','raw'),(float('inf'),'raw'),('1,,200','raw'),('$1$','money'),('40m','raw'),('12%','money_m'),('14x','percent'),('1 2','raw'),('€40m','money_m'),('$12','percent')])
def test_bad_or_ambiguous_figures_are_rejected(value,unit):
    with pytest.raises(ValueError):data.number(value,unit)

def test_changed_workbook_values_change_both_marks_and_printed_numbers(compiled):
    _,entry,_=compiled['investigations/profit-vs-cash-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    before=data.draw(r,v,INK);v.update({'input-net-income':'$125m','input-operating-cash':'$65m'})
    after=data.draw(r,v,INK);labels={l['slot']:l['text'] for l in data.labels(r,v,INK)}
    assert before!=after
    assert labels['summary-0']=='$60m' and labels['summary-1']=='52%'
    assert labels['metric-0']=='$125m' and labels['metric-1']=='$65m'
    with pytest.raises(ValueError):data.draw(r,{**v,'x':50},INK)
    with pytest.raises(ValueError):data.draw(r,{k:x for k,x in v.items() if k!='input-net-income'},INK)

def test_manifest_alone_builds_the_writer_menu_and_fill(compiled):
    for _,entry,_ in compiled.values():
        text=contracts.writer_menu(entry);values=contracts.example_fill(entry)
        assert entry['purpose'] in text and entry['caution'] in text
        assert all(isinstance(v,str) for v in values.values())
        prepared=contracts.prepare(entry,values,INK)
        assert not any(entry['slots'][k].get('region') for k in prepared['values'])
        assert contracts.script_example(entry).startswith('[PLATE: '+entry['key']+' | ')
        if 'data-area' in entry['slots']:
            assert set(entry['slots']['data-area']['inputSlots'])<=values.keys()
            assert prepared['nodes']
    _,entry,_=compiled['investigations/profit-vs-cash-16x9'];values=contracts.example_fill(entry)
    values.update({'input-net-income':'$125m','input-operating-cash':'$65m'})
    assert contracts.prepare(entry,values,INK)['values']['summary-0']=='$60m'
    with pytest.raises(ValueError):contracts.prepare(entry,{**values,'summary-0':'$900m'},INK)

def test_independent_drawdown_and_reconciliation(compiled):
    _,entry,_=compiled['charts/underwater-drawdown-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    labels={l['slot']:l['text'] for l in data.labels(r,v,INK)}
    assert labels['summary-value-0']=='-30%' and labels['summary-value-1']=='0%'
    item=next(i for i in ITEMS if i['drawer']=='research' and i['definition'].get('model')=='asset_bridge')
    _,entry,_=compiled[item['key']+'-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    v['input-closing']='999999'
    with pytest.raises(ValueError,match='reconcile'):data.draw(r,v,INK)

def test_region_geometry_is_published_not_a_writer_input(compiled):
    _,entry,_=compiled['investigations/profit-vs-cash-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    translated={**r,'x':r['x']+37,'y':r['y']+23}
    a=data.draw(r,v,INK);b=data.draw(translated,v,INK)
    for first,second in zip(a,b):
        if first['tag']=='rect':
            assert second['attrs']['x']==pytest.approx(first['attrs']['x']+37)
            assert second['attrs']['y']==pytest.approx(first['attrs']['y']+23)
            assert second['attrs']['width']==first['attrs']['width']

def test_blank_raster_never_calls_a_text_renderer(tmp_path,compiled):
    _,entry,nodes=compiled['investigations/profit-vs-cash-16x9'];path=tmp_path/'blank.png'
    with patch.object(ImageDraw.ImageDraw,'text',side_effect=AssertionError('baked type')):build_all.raster(entry,nodes,INK,path)
    with Image.open(path) as image:
        assert image.size==(3840,2160)
        assert image.getpixel((1920,1200))==(244,242,234)

def test_one_cli_build_is_repeatable_and_uses_the_kit_table_shape(tmp_path):
    outputs=[tmp_path/'one',tmp_path/'two']
    for out in outputs:
        result=subprocess.run([sys.executable,str(ROOT/'design/build_all.py'),'--out',str(out),'--ground','paper','--scale','2','--only','investigations/profit-vs-cash','--only','chapters/missing-half'],cwd=tmp_path,text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        assert {p.suffix for p in out.rglob('*') if p.is_file()}=={'.png','.json'}
        for file in out.glob('*/manifest.json'):
            manifest=json.loads(file.read_text())
            assert manifest['bakedText'] is False
            for key,entry in manifest['plates'].items():
                path=file.parent/entry['files']['base']
                assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['files']['frames'][0]['hash']
                with Image.open(path) as im:assert list(im.size)==entry['delivered']
    digest=lambda out:{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    assert digest(outputs[0])==digest(outputs[1])
    spec=importlib.util.spec_from_file_location('design_test_ingest',ROOT/'scripts/ingest_kit.py');ingest=importlib.util.module_from_spec(spec);spec.loader.exec_module(ingest)
    # New families intentionally remain outside EXPECTED_FAMILIES until the
    # future ingest adapter is authorised. Their tables use its existing shape.
    tables={key:entry for f in outputs[0].glob('*/manifest.json') for key,entry in ingest._plate_table(json.loads(f.read_text())).items()}
    assert len(tables)==4
    bad=tmp_path/'bad'
    result=subprocess.run([sys.executable,str(ROOT/'design/build_all.py'),'--out',str(bad),'--only','missing'],capture_output=True)
    assert result.returncode!=0 and not bad.exists()
