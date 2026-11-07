"""The unwired delivery is source-only, text-free and driven by workbook slots."""
from __future__ import annotations
import ast
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
from design import build_all,contracts,core,data,motion,sources,workbook
from pipeline.models import MILLIONS_FIELDS,RATE_FIELDS

ROOT=Path(__file__).resolve().parents[1]
ITEMS=json.loads((ROOT/'design/catalog.json').read_text())['plates']
TOKENS=json.loads((ROOT/'kit/design-tokens.json').read_text())
INK=TOKENS['hours']['night']['plateInk']['paper']
DATA_ITEMS=[i for i in ITEMS if core.needs_data(i)]
SCALED_MONEY_ITEMS=[i for i in DATA_ITEMS if any(m['unit'] in ('money_m','money_b','shares_m') for m in i['inputMetadata'].values())]

@pytest.fixture(scope='module')
def compiled():
    return {item['key']+'-'+aspect:(item,*build_all.compile_plate(item,aspect,INK,2)) for item in ITEMS for aspect in ('16x9','9x16')}

def test_unique_concepts_and_published_kit_motion(compiled):
    assert len(ITEMS)==188 and len(compiled)==376 and len(DATA_ITEMS)==125
    assert len({i['key'] for i in ITEMS})==188
    assert sum('motion' in i for i in ITEMS)==121
    published={}
    for f in (ROOT/'kit').glob('*/manifest.json'):
        m=json.loads(f.read_text());table=m.get('plates',m.get('assets',{}))
        if isinstance(table,dict):published.update(table)
    assert set(compiled).isdisjoint(published)
    kit=json.loads((ROOT/'design/kit-motion.json').read_text())['plates']
    assert len(kit)==104
    anchors=json.loads((ROOT/'kit/emit/motion.json').read_text())['anchors']['plates']
    native_counts={'line-draw':0,'highlight':0}
    for key,recipe in kit.items():
        assert key in published
        motion.validate(recipe,published[key]['slots'],anchors[key],published[key]['typeRoles'])
        assert len(recipe['optionalMoves'])==1
        for step in recipe['steps']:
            assert step['slot'] in published[key]['slots']
            if 'move' in step:native_counts[step['move']]+=1
        for move in native_counts:
            assert bool(anchors[key].get(move))==any(step.get('move')==move for step in recipe['steps'])
    assert native_counts=={'line-draw':16,'highlight':13}

def test_common_manifest_and_text_free_artwork(compiled):
    chapter_types=build_all.chapter_types()
    for key,(item,entry,nodes) in compiled.items():
        assert re.fullmatch(r'[a-z0-9-]+/[a-z0-9-]+-(16x9|9x16)',key)
        assert not any(p in key for p in ('vol2','library'))
        assert entry['ground']=='paper' and entry['bakedText'] is False
        assert entry['exportScale']==2 and entry['delivered']==[v*2 for v in entry['canvas']]
        assert entry['playback']=='static' and entry['fps']==0 and entry['frameCount']==1
        assert isinstance(entry['slots'],dict) and entry['purpose'] and entry['caution']
        assert set(entry['chapterTypes'])<=chapter_types and entry['sectors']==[]
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
                assert name in entry['slots']
                note=entry['slots'][name]['note']
                if entry['slots'][name].get('assumption'):
                    assert 'fact-check does not check'in note;continue
                assert re.match(r'(History|Quarters|Snapshot)![a-z0-9_]+, |From the filing: ',note)
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
        motion.validate(entry['motion'],entry['slots'])
        assert 3<=len(entry['motion']['steps'])<=6
        for step in entry['motion']['steps']:
            assert step['slot'] in entry['slots']
            if 'cueSlot' in step:assert step['cueSlot'] in entry['slots']
            assert step.get('action') in ('appear','clip-in','draw-on','grow') or step.get('move')
        if 'data-area' in entry['slots']:
            reveal=next(s for s in entry['motion']['steps'] if s['slot']=='data-area')
            furniture={n for n,s in entry['slots'].items() if s['role'] in ('tick','axis','legend','unit','period')}
            assert furniture<=set(motion.members(reveal))
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

@pytest.mark.parametrize('value,unit,expected',[('$1.2bn','money_m',1200),(1200000000,'money_m',1200),('1,200,000,000','money_m',1200),('$120','money_m',.00012),('50m','shares_m',50),(50000000,'shares_m',50),('50,000,000','shares_m',50),('−12.5%','percent',-12.5),('($40m)','money_m',-40),('14x','multiple',14),('1,250.5','raw',1250.5)])
def test_script_number_units(value,unit,expected):assert data.number(value,unit)==expected

@pytest.mark.parametrize('value,unit',[(True,'raw'),('NaN','raw'),(float('inf'),'raw'),('1,,200','raw'),('$1$','money'),('40m','raw'),('12%','money_m'),('14x','percent'),('1 2','raw'),('€40m','money_m'),('$12','percent')])
def test_bad_or_ambiguous_figures_are_rejected(value,unit):
    with pytest.raises(ValueError):data.number(value,unit)

@pytest.mark.parametrize('item',SCALED_MONEY_ITEMS,ids=lambda i:i['key'])
def test_each_money_and_share_input_rejects_a_missing_magnitude_before_drawing(item,compiled):
    assert len(SCALED_MONEY_ITEMS)==86
    for aspect in ('16x9','9x16'):
        _,entry,_=compiled[item['key']+'-'+aspect];region=entry['slots']['data-area']
        fill=contracts.example_fill(entry);values={k:fill[k] for k in region['inputSlots']}
        for name,binding in region['recipe']['bindings'].items():
            if binding['unit'] not in ('money_m','money_b','shares_m'):continue
            for raw in ('100','-100','(100)',100):
                bad={**values,name:raw}
                # The unit guidance must precede a model-bound, division or
                # reconciliation error, and no geometry may be constructed.
                with patch.object(core,'assemble',side_effect=AssertionError('drew an invisible input')):
                    for render in (data.draw,data.labels):
                        with pytest.raises(ValueError,match='non-zero but would display as zero') as error:render(region,bad,INK)
                        assert name in str(error.value) and 'Add m or bn' in str(error.value)
                    if isinstance(raw,str):
                        with pytest.raises(ValueError,match='Add m or bn'):contracts.prepare(entry,{**fill,name:raw},INK)

@pytest.mark.parametrize('key,path,bad,good,display',[
    ('stock/filing-reserve-release',['inputs','release'],'0.004m','0.006m','$0.01m'),
    ('finance/equity-to-ev',['debt'],'0.004m','0.006m','$0.01m'),
    ('investigations/profit-vs-cash',['operating_cash'],'0.04m','0.06m','$0.1m'),
    ('charts/transaction-network',['data','amounts',0],'0.4m','0.6m','$1m'),
    ('stock/risk-volume-context',['inputs','daily_volume'],'0.004m','0.006m','0.01m'),
    ('finance/revenue-engine',['net_revenue_per_order'],'$0.004','$0.006','$0.01'),
])
def test_zero_guard_matches_the_plate_precision_even_with_an_explicit_unit(key,path,bad,good,display,compiled):
    for aspect in ('16x9','9x16'):
        _,entry,_=compiled[key+'-'+aspect];region=entry['slots']['data-area'];fill=contracts.example_fill(entry)
        name=next(n for n,b in region['recipe']['bindings'].items() if b['path']==path)
        with pytest.raises(ValueError,match='Add m or bn'):contracts.prepare(entry,{**fill,name:bad},INK)
        result=contracts.prepare(entry,{**fill,name:good},INK)
        assert display in result['values'].values()

def test_tiny_per_share_money_and_scaling_underflow_are_also_rejected(compiled):
    for _,entry,_ in compiled.values():
        if entry['aspect']!='16x9' or 'data-area' not in entry['slots']:continue
        region=entry['slots']['data-area'];values={k:entry['example'][k] for k in region['inputSlots']}
        for name,b in region['recipe']['bindings'].items():
            if b['unit']!='money':continue
            with pytest.raises(ValueError,match='Add m or bn'):data.draw(region,{**values,name:'0.00001'},INK)
    _,entry,_=compiled['investigations/profit-vs-cash-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    assert data.number(5e-324,'money_m')==0  # underflow cannot masquerade as a genuine zero
    with pytest.raises(ValueError,match='Add m or bn'):data.draw(r,{**v,'input-operating-cash':5e-324},INK)

@pytest.mark.parametrize('zero',['0','-0','0m','-$0m','(0)','0.000',0,0.0,-0.0])
def test_true_zero_inputs_and_calculated_zeroes_remain_valid(zero,compiled):
    _,entry,_=compiled['investigations/profit-vs-cash-16x9'];r=entry['slots']['data-area'];v={k:entry['example'][k] for k in r['inputSlots']}
    v['input-operating-cash']=zero
    assert data.draw(r,v,INK)
    assert next(l['text'] for l in data.labels(r,v,INK) if l['slot']=='metric-1')=='$0m'
    v['input-operating-cash']=v['input-net-income']
    assert next(l['text'] for l in data.labels(r,v,INK) if l['slot']=='summary-0')=='$0m'

def test_restatement_eps_uses_dollars_and_not_millions(compiled):
    _,entry,_=compiled['investigations/restatement-16x9'];r=entry['slots']['data-area'];fill=contracts.example_fill(entry)
    original=next(n for n,b in r['recipe']['bindings'].items() if b['path']==['rows',2,'original'])
    restated=next(n for n,b in r['recipe']['bindings'].items() if b['path']==['rows',2,'restated'])
    assert entry['slots'][original]['sourceUnit']==entry['slots'][restated]['sourceUnit']=='money'
    result=contracts.prepare(entry,{**fill,original:'1.6',restated:'0.6'},INK)
    assert result['values']['value-2-0']=='$1.6' and result['values']['value-2-1']=='$0.6'

def test_sources_match_the_actual_workbook_and_financial_units(compiled):
    tables=workbook.schema(ROOT/'templates/dennis_data_template.xlsx')
    references=set();filings=0
    share_keys={'shares_out','shares_dill_out','diluted_shares','avg_volume_3m'}
    for _,entry,_ in compiled.values():
        if 'data-area' not in entry['slots']:continue
        for name,binding in entry['slots']['data-area']['recipe']['bindings'].items():
            src=binding['source'];unit=binding['unit'];slot=entry['slots'][name]
            if binding.get('assumption'):
                assert src is None and slot['factCheck']is False and 'fact-check does not check'in slot['note'];continue
            workbook.validate_source(src,tables)
            assert unit in sources.UNIT_LABELS and slot['sourceUnit']==unit
            assert slot['source']==src and not slot.get('default')
            if src['kind']=='filing':
                filings+=1
                assert slot['note'].startswith('From the filing: '+src['location'])
                assert 'Not confirmed by a workbook row.' in slot['note']
                continue
            references.add((src['sheet'],src['field']))
            assert slot['note'].startswith(f'{src["sheet"]}!{src["field"]}, {src["period"]}.')
            field=src['field']
            if src.get('calculation'):continue
            if field in share_keys:assert unit=='shares_m'
            elif field in MILLIONS_FIELDS:assert unit in ('money','money_m','money_b')
            elif field in RATE_FIELDS:assert unit=='percent'
            elif field in ('price','eps','eps_street','eps_consensus'):assert unit=='money'
            if src['sheet']=='Snapshot':assert src['period']=='as-of'
    assert len(references)>=30 and filings>1000
    with pytest.raises(ValueError,match='Unknown workbook row'):
        workbook.validate_source({'kind':'workbook','sheet':'History','field':'auditor_fee','period':'FY-0'},tables)
    with pytest.raises(ValueError,match='Unsupported workbook period'):
        workbook.validate_source({'kind':'workbook','sheet':'History','field':'capex','period':'FY-7'},tables)
    item=deepcopy(DATA_ITEMS[0]);item['inputMetadata']={}
    with pytest.raises(ValueError,match='Missing authored source metadata'):data.bindings(item,core.assemble(item,'16x9')[0])

def test_whole_workbook_amounts_and_written_magnitudes_produce_the_same_labels(compiled):
    checked=0
    for _,entry,_ in compiled.values():
        if entry['aspect']!='16x9' or 'data-area' not in entry['slots']:continue
        region=entry['slots']['data-area'];written={k:entry['example'][k] for k in region['inputSlots']};whole=deepcopy(written)
        for name,binding in region['recipe']['bindings'].items():
            unit=binding['unit']
            if binding['kind']=='number':assert entry['slots'][name].get('inputOnly')
            if binding['kind']=='number' and unit in ('money','money_m','money_b','shares_m'):
                whole[name]=str(data.number(written[name],unit)*sources.SCALED_UNITS.get(unit,1));checked+=1
        assert data.labels(region,written,INK)==data.labels(region,whole,INK)
        fill=contracts.example_fill(entry)
        assert contracts.prepare(entry,{**fill,**written},INK)==contracts.prepare(entry,{**fill,**whole},INK)
        before=data.draw(region,written,INK);after=data.draw(region,whole,INK)
        assert len(before)==len(after)
        for a,b in zip(before,after):
            assert a['tag']==b['tag'] and a['attrs']==pytest.approx(b['attrs'])
    assert checked>300

def test_units_are_computed_and_the_reporting_label_cannot_change_them(compiled):
    for _,entry,_ in compiled.values():
        menu=contracts.writer_slots(entry)
        for name,slot in entry['slots'].items():
            if slot.get('unitLabel'):assert name not in menu and 'default' not in slot
    _,entry,_=compiled['charts/capex-depreciation-vintages-16x9']
    values=contracts.example_fill(entry);values['input-period']='FY21-FY25'
    controls=entry['slots']['data-area']['recipe']['bindings']
    capex=next(k for k,b in controls.items() if b['path']==['data','capex',0])
    first=contracts.prepare(entry,{**values,capex:'($1.2bn)'},INK)
    second=contracts.prepare(entry,{**values,capex:'-1200000000'},INK)
    assert first==second and first['values']['period']=='FY21-FY25 / $m'
    assert first['values']['chart-units'].endswith('$m')
    for label in ('FY25 / $m','FY25 / bn','FY25 / million','FY25 / shares'):
        with pytest.raises(ValueError,match='unit label'):contracts.prepare(entry,{**values,'input-period':label},INK)
    with pytest.raises(ValueError,match='Unknown or computed'):contracts.prepare(entry,{**values,'period':'FY25 / $bn'},INK)

def test_sensitive_definitions_are_not_mapped_to_different_workbook_metrics(compiled):
    for key,paths in {
        'stock/debt-covenant-room':[['inputs','debt'],['inputs','ebitda']],
        'stock/debt-usable-net-debt':[['inputs','cash']],
        'investigations/cash-availability':[['total']],
        'finance/cash-runway':[['cash']],
        'stock/earnings-second-half-hurdle':[['inputs','first_half'],['inputs','prior_second_half']],
    }.items():
        _,entry,_=compiled[key+'-16x9'];bindings=entry['slots']['data-area']['recipe']['bindings']
        for path in paths:assert next(b for b in bindings.values() if b['path']==path)['source']['kind']=='filing'
    _,entry,_=compiled['investigations/repeated-addbacks-16x9'];bindings=entry['slots']['data-area']['recipe']['bindings']
    assert [next(b for b in bindings.values() if b['path']==['charge_'+s])['source']['period'] for s in ('a','b','c')]==['FY-2','FY-1','FY-0']

def test_semantic_type_roles_are_shared_and_keep_slot_inks(compiled):
    allowed={'headline','caption','source','period','kicker','unit','legend','tick','axis','statement','body','detail','huge','figure','value','label','ref'}
    for _,entry,_ in compiled.values():
        assert set(entry['typeRoles'])<=allowed
        for name,slot in entry['slots'].items():
            if slot.get('region'):continue
            assert slot['colour'] in core.INK_NAMES
            assert entry['typeRoles'][slot['role']]['maxChars']<=slot['maxChars']
        for measured in entry['typeAudit']:
            slot=entry['slots'][measured['slot']]
            assert measured['role']==slot['role']
            assert measured['size']==entry['typeRoles'][slot['role']]['size']
    _,entry,_=compiled['charts/capex-depreciation-vintages-16x9']
    ticks=[s for s in entry['slots'].values() if s['role']=='tick']
    assert len(ticks)>=8 and len(entry['typeRoles'])<len(entry['slots'])/2

def test_motion_rejects_unspoken_cues_and_unpublished_moves(compiled):
    _,entry,_=compiled['charts/capex-depreciation-vintages-16x9'];recipe=deepcopy(entry['motion'])
    reveal=next(s for s in recipe['steps'] if s['slot']=='data-area')
    reveal['cueSlot']=next(n for n in reveal['includeSlots'] if entry['slots'][n]['role']=='tick')
    with pytest.raises(ValueError,match='Chart furniture'):motion.validate(recipe,entry['slots'])
    recipes=json.loads((ROOT/'design/kit-motion.json').read_text())['plates']
    key='cards/definition-16x9';recipe=deepcopy(recipes[key])
    plate=json.loads((ROOT/'kit/cards/manifest.json').read_text())['plates'][key]
    anchors=json.loads((ROOT/'kit/emit/motion.json').read_text())['anchors']['plates'][key]
    step=next(s for s in recipe['steps'] if s.get('move')=='highlight');step['move']='line-draw'
    with pytest.raises(ValueError,match='published anchor'):motion.validate(recipe,plate['slots'],anchors,plate['typeRoles'])
    recipe=deepcopy(recipes[key]);recipe['optionalMoves'][0]['enabled']=True
    with pytest.raises(ValueError,match='reserved for Valentin'):motion.validate(recipe,plate['slots'],anchors,plate['typeRoles'])

def test_source_files_parse_on_the_render_box_python_311():
    files=[p for p in (ROOT/'design').glob('*.py') if p.name not in ('build_gallery.py','build_preview.py')]
    files+=list((ROOT/'design/drawings').glob('*.py'))
    for file in files:ast.parse(file.read_text(),filename=str(file),feature_version=(3,11))

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
