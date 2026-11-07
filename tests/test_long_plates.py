"""The Round 3 proposal contract, without production registration."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest
from PIL import Image,ImageFont
from pipeline.series import paint
from design import build_all,contracts,core,longs,workbook

ROOT=Path(__file__).resolve().parents[1]
CATALOG=json.loads((ROOT/'design/longs.json').read_text())
ITEMS=CATALOG['plates']
INK=json.loads((ROOT/'kit/design-tokens.json').read_text())['hours']['night']['plateInk']['paper']

@pytest.fixture(scope='module')
def compiled():
    return {entry['key']:(item,entry,nodes)
        for item in ITEMS for aspect in item.get('aspects',['16x9','9x16'])
        for variant in item.get('variants',[None])
        for entry,nodes in [build_all.compile_plate(item,aspect,INK,2,variant)]}

def entry(compiled,key,aspect='16x9'):
    return compiled[key+'-'+aspect][1]

def test_part_one_has_every_requested_concept_variant_and_new_press_half(compiled):
    one=[i for i in ITEMS if i['part']==1]
    assert len(one)==9
    assert sum(e['longRecipe']['item']['part']==1 for _,e,_ in compiled.values())==27
    assert len([k for k in compiled if k.startswith('investigations/mechanism-steps-')])==12
    assert 'paper/press-release-16x9'in compiled and 'paper/press-release-9x16'not in compiled
    assert entry(compiled,'paper/press-release')['existingCounterpart']=='paper/press-release-9x16'
    assert {i['key'] for i in one}=={'investigations/cast-board','charts/collapse-timeline','investigations/mechanism-steps','charts/who-paid','investigations/where-it-ended','figures/loss-clock','tables/toy-trade','paper/press-release','chapters/red-flag-checklist'}

def test_shared_delivery_rules_and_source_contract(compiled):
    schema=workbook.schema(ROOT/'templates/dennis_data_template.xlsx')
    for item,e,nodes in compiled.values():
        assert e['ground']=='paper' and e['exportScale']==2 and e['bakedText']is False
        assert e['delivered']==[v*2 for v in e['canvas']]
        assert e['sectors']==[] and set(e['chapterTypes'])<=build_all.chapter_types()
        assert set(e['typeRoles'])<=set(longs.STYLE)
        assert not {'brand','counter','file','takeaway'}&e['slots'].keys()
        if item['model']!='press':assert 'source'not in e['slots']
        assert all(n['tag']in('rect','circle','path') for n in nodes)
        assert all(n['attrs'].get('fill')in core.INK_NAMES for n in nodes)
        for n,s in e['slots'].items():
            assert s['note'] and s.get('sourceUnit')in sources_units() if not s.get('region') else s['note']
            if s.get('source'):workbook.validate_source(s['source'],schema)
            if s.get('enum'):assert all(v in s['note'] for v in s['enum'])
        longs.validate_motion(e['motion'],e['slots'])
        assert 3<=len(e['motion']['steps'])<=6
        menu=contracts.writer_menu(e);assert e['purpose']in menu
        assert contracts.script_example(e).startswith('[PLATE: '+e['key'])
        prepared=contracts.prepare(e,contracts.example_fill(e),INK)
        assert not any(e['slots'][n].get('region') for n in prepared['values'])

def sources_units():
    from design.sources import UNIT_LABELS
    return UNIT_LABELS

@pytest.mark.parametrize('item',ITEMS,ids=lambda i:i['key'])
def test_every_new_drawer_is_pure_and_paintable(item,compiled):
    for _,e,_ in [v for v in compiled.values() if v[0]['key']==item['key']]:
        fill=contracts.example_fill(e);snapshot=deepcopy((e,fill,INK));nodes=[]
        with patch('builtins.open',side_effect=AssertionError('I/O')),patch.object(Path,'read_text',side_effect=AssertionError('I/O')),patch.object(subprocess,'run',side_effect=AssertionError('subprocess')),patch.object(Image,'new',side_effect=AssertionError('image')),patch.object(ImageFont,'truetype',side_effect=AssertionError('font')):
            p=contracts.prepare(e,fill,INK)
            for r in e['slots'].values():
                if r.get('renderer')!='design.longs.draw':continue
                nodes.extend(longs.draw(r,fill,INK));assert longs.labels(r,fill,INK)
        assert (e,fill,INK)==snapshot
        assert all(set(n)=={'tag','attrs'} and n['tag']in('rect','circle','path') for n in nodes)
        canvas=Image.new('RGBA',tuple(e['canvas']),INK['ground']);paint(canvas,nodes,1);canvas.close()
        assert p['values']

def test_collapse_uses_a_plain_axis_when_no_price_exists(compiled):
    e=entry(compiled,'charts/collapse-timeline');v=contracts.example_fill(e)
    p=contracts.prepare(e,v,INK);assert p['values']['drop']=='-96%'
    assert p['motion']['steps'][0].get('move')is None
    v.update({'clock-unit':'DAYS','axis-start':'2020-01-01','axis-end':'2020-01-06','event-count':'1','when-1':'2020-01-02','price-data':'2020-01-01,$100;2020-01-02,$80;2020-01-06,$4'})
    p=contracts.prepare(e,v,INK)
    assert p['motion']['steps'][0]['move']=='line-draw' and p['values']['drop']=='-96%'
    with pytest.raises(ValueError,match='dated axis'):contracts.prepare(e,{**v,'when-1':'2019-01-01'},INK)

def test_bill_uses_one_scale_and_does_not_sum_overlapping_losses(compiled):
    e=entry(compiled,'charts/who-paid');v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
    assert p['values']['ratio']=='40x'
    r=e['slots']['bill-area'];lossnodes=longs.draw(r,v,INK);fine=longs.draw(e['slots']['fine-bar'],v,INK)
    assert len(lossnodes)==6 and len(fine)==1
    assert fine[0]['attrs']['width']/max(n['attrs']['width'] for n in lossnodes)==pytest.approx(2.5/100)
    assert p['boxes']['party-1'][1]<p['boxes']['party-6'][1]
    with pytest.raises(ValueError,match='paper loss'):contracts.prepare(e,{**v,'kind-1':'PAPER LOSS'},INK)
    assert contracts.prepare(e,{**v,'kind-1':'PAPER LOSS','note-1':'paper loss'},INK)['values']['note-1']=='paper loss'

def test_statuses_and_stop_mark_are_driven_by_the_record(compiled):
    e=entry(compiled,'investigations/cast-board');v=contracts.example_fill(e)
    with pytest.raises(ValueError,match='must be one of'):contracts.prepare(e,{**v,'status-1':'GUILTY'},INK)
    e=entry(compiled,'investigations/mechanism-steps-5-step-loop');v=contracts.example_fill(e)
    a=contracts.prepare(e,{**v,'stop-at':'1'},INK);b=contracts.prepare(e,{**v,'stop-at':'5'},INK)
    assert a['boxes']['stop-mark']!=b['boxes']['stop-mark']
    assert a['boxes']['stop-mark'][0]==pytest.approx(a['boxes']['step-1'][0]-27)
    assert 'loop-label'in e['slots']
    assert 'loop-label'not in entry(compiled,'investigations/mechanism-steps-3-step')['slots']

def test_an_untried_settlement_does_not_fill_the_trial_dot(compiled):
    e=entry(compiled,'investigations/where-it-ended');v=contracts.example_fill(e)
    r=e['slots']['ladder-area'];a=longs.draw(r,v,INK);circles=[n for n in a if n['tag']=='circle']
    assert circles[0]['attrs']['fill']==INK['subject']
    assert circles[2]['attrs']['fill']==INK['ground']
    assert circles[3]['attrs']['fill']==INK['subject']
    b=longs.draw(r,{**v,'tried-1':'YES'},INK)
    assert [n for n in b if n['tag']=='circle'][2]['attrs']['fill']==INK['subject']

def test_clock_rest_points_are_only_the_documented_checkpoints(compiled):
    e=entry(compiled,'figures/loss-clock');v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
    runs=[s for s in p['motion']['steps'] if s.get('move')=='clock-run']
    assert len(runs)==1 and runs[0]['toValueSlot']=='total-1'
    assert runs[0]['continuousBetweenCheckpoints'] and runs[0]['restOnlyAtDocumentedCheckpoints']
    with pytest.raises(ValueError,match='over 45 minutes'):contracts.prepare(e,{**v,'caption':'By 09:45 it had lost $10m'},INK)
    v.update({'at-1':'09:45','total-1':'20m','at-2':'10:15','total-2':'100m'})
    assert len([s for s in contracts.prepare(e,v,INK)['motion']['steps'] if s.get('move')=='clock-run'])==2
    with pytest.raises(ValueError,match='end time'):contracts.prepare(e,{**v,'at-2':'10:00'},INK)
    with pytest.raises(ValueError,match='cannot decrease'):contracts.prepare(e,{**v,'total-2':'10m'},INK)

def test_toy_trade_requires_its_tag_and_reconciles_every_row(compiled):
    e=entry(compiled,'tables/toy-trade');v=contracts.example_fill(e)
    assert contracts.prepare(e,v,INK)['values']['total-3']=='$1,000,000'
    with pytest.raises(ValueError,match='Missing required'):contracts.prepare(e,{n:x for n,x in v.items() if n!='tag'},INK)
    with pytest.raises(ValueError,match='must be one of'):contracts.prepare(e,{**v,'tag':'REAL FIGURES'},INK)
    with pytest.raises(ValueError,match='does not add up'):contracts.prepare(e,{**v,'total-2':'$10'},INK)
    assert e['factCheck']['skipWhen']['values']==['EXAMPLE','TOY NUMBERS']

def test_press_release_highlight_is_a_verbatim_sentence(compiled):
    e=entry(compiled,'paper/press-release');v=contracts.example_fill(e)
    with pytest.raises(ValueError,match='copied exactly'):contracts.prepare(e,{**v,'marked-sentence':'Not in the body.'},INK)
    with pytest.raises(ValueError,match='D2.14'):contracts.prepare(e,{**v,'body-ref':'page 4'},INK)
    native=json.loads((ROOT/'kit/paper/manifest.json').read_text())['plates']['paper/press-release-9x16']
    assert set(native['slots'])<=e['slots'].keys()

def test_red_flags_publish_both_sources_and_never_draw_a_finding(compiled):
    e=entry(compiled,'chapters/red-flag-checklist');v=contracts.example_fill(e)
    assert 'document sentence'in e['slots']['figure-1']['note']
    assert 'History!accounts_receivable'in e['slots']['figure-2']['note']
    assert e['slots']['figure-2']['source']['pending']is True
    for word in ('FRAUD','fake','cooked'):
        with pytest.raises(ValueError,match='never a fraud finding'):contracts.prepare(e,{**v,'title':word+' CHECK'},INK)

@pytest.mark.parametrize('key',['charts/who-paid','figures/loss-clock'])
def test_new_money_inputs_share_the_zero_guard(key,compiled):
    e=entry(compiled,key);v=contracts.example_fill(e);name='fine-amount' if key.endswith('who-paid') else 'total-1'
    with pytest.raises(ValueError,match='Add m or bn'):contracts.prepare(e,{**v,name:'100'},INK)
