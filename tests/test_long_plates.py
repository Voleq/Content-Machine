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
        assert len(e['motion']['steps'])==2 if item['model']=='question' else 3<=len(e['motion']['steps'])<=6
        menu=contracts.writer_menu(e);assert e['purpose']in menu
        assert contracts.script_example(e).startswith('[PLATE: '+e['key'])
        prepared=contracts.prepare(e,contracts.example_fill(e),INK)
        assert not any(e['slots'][n].get('region') for n in prepared['values'])

def test_complete_catalogue_is_unique_and_new_keys_do_not_replace_kit_plates(compiled):
    items=build_all.catalog_items()
    assert len(items)==203 and len({i['key'] for i in items})==203
    assert len(compiled)==39 and len(ITEMS)==15
    assert sum(len(i.get('aspects',['16x9','9x16']))*len(i.get('variants',[None])) for i in items)==415
    published=set()
    for f in (ROOT/'kit').glob('*/manifest.json'):
        m=json.loads(f.read_text());table=m.get('plates',m.get('assets',{}))
        if isinstance(table,dict):published.update(table)
    assert set(compiled).isdisjoint(published)
    for _,e,_ in compiled.values():
        w,h=e['canvas']
        for n,s in e['slots'].items():
            assert s['x']>=0 and s['y']>=0 and s['x']+s['w']<=w and s['y']+s['h']<=h,n

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
    assert runs[0]['cueAt']=='checkpoint-end'
    assert 'live-total'not in p['motion']['steps'][0]['includeSlots']
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
    with pytest.raises(ValueError,match='does not add up'):contracts.prepare(e,{**v,'total-2':'$1.0000000001'},INK)
    assert e['factCheck']['skipWhen']['values']==['EXAMPLE','TOY NUMBERS']

def test_press_release_highlight_is_a_verbatim_sentence(compiled):
    e=entry(compiled,'paper/press-release');v=contracts.example_fill(e)
    with pytest.raises(ValueError,match='copied exactly'):contracts.prepare(e,{**v,'marked-sentence':'Not in the body.'},INK)
    with pytest.raises(ValueError,match='D2.14'):contracts.prepare(e,{**v,'body-ref':'page 4'},INK)
    native=json.loads((ROOT/'kit/paper/manifest.json').read_text())['plates']['paper/press-release-9x16']
    assert set(native['slots'])<=e['slots'].keys()
    assert contracts.prepare(e,{n:v[n] for n in native['slots'] if n!='mark-area'},INK)['values']['body']==v['body']

def test_promise_ledger_resolves_real_fields_units_and_row_limits(compiled):
    wide=entry(compiled,'chapters/promise-ledger');phone=entry(compiled,'chapters/promise-ledger','9x16')
    assert 'promise-4'in wide['slots'] and 'promise-4'not in phone['slots']
    assert wide['slots']['promise-1']['maxLines']==2
    fill=contracts.example_fill(wide);p=contracts.prepare(wide,fill,INK)
    assert p['units']['result-1']=='money_m' and p['units']['result-4']=='money'
    assert p['sources']['result-4']['field']=='eps'
    with pytest.raises(ValueError,match='actual workbook|Unknown workbook'):contracts.prepare(wide,{**fill,'result-field-1':'invented_revenue'},INK)
    with pytest.raises(ValueError,match='period'):contracts.prepare(wide,{**fill,'result-sheet-1':'History'},INK)
    with pytest.raises(ValueError,match='Add m or bn'):contracts.prepare(wide,{**fill,'result-1':'100'},INK)
    only={n:v for n,v in fill.items() if not n.endswith(('-2','-3','-4'))};only['row-count']='1'
    assert contracts.prepare(wide,only,INK)['values']['promise-1']==fill['promise-1']

def test_a_vague_promise_is_only_dropped_after_it_disappears(compiled):
    e=entry(compiled,'chapters/promise-ledger');v=contracts.example_fill(e)
    v.update({'promise-1':'We will be the trusted partner.','target-period-1':''})
    with pytest.raises(ValueError,match='only be DROPPED'):contracts.prepare(e,v,INK)
    v['mark-1']='DROPPED'
    with pytest.raises(ValueError,match='stopped mentioning'):contracts.prepare(e,v,INK)
    assert contracts.prepare(e,{**v,'no-longer-mentioned-1':'YES','result-1':''},INK)['values']['mark-1']=='DROPPED'

def test_form4_only_counts_open_market_codes_and_quiets_routine_sales(compiled):
    e=entry(compiled,'charts/insider-trades');v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
    assert {n:p['values'][n] for n in ('bought-12m','sold-12m','buyers','sellers')}=={'bought-12m':'$1m','sold-12m':'$2.5m','buyers':'1','sellers':'2'}
    marks=longs.draw(e['slots']['trade-marks'],v,INK)
    assert len(marks)==4 and sum(n['attrs']['fill']==INK['quiet'] for n in marks)==2
    assert p['boxes']['trade-focus'][0]>e['slots']['price-area']['x']
    empty=contracts.prepare(e,{**v,'trade-data':'','focus-trade':'0'},INK)
    assert empty['values']['bought-12m']=='$0' and empty['values']['buyers']=='0'
    assert empty['motion']['steps'][-1].get('move')is None
    small=contracts.prepare(e,{**v,'trade-data':'2026-03-03,P,$100,Director A,NO,NO','focus-trade':'1'},INK)
    assert small['values']['bought-12m']=='$100'  # never show a real small feed total as zero million
    assert 'price-data='not in contracts.script_example(e) and 'trade-data='not in contracts.script_example(e)
    assert 'price-data (max'not in contracts.writer_menu(e)
    assert e['slots']['price-data']['sourceManaged']is True

def test_shared_index_uses_observed_common_dates_and_one_axis(compiled):
    e=entry(compiled,'charts/stock-vs-driver');v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
    assert p['values']['stock-change']=='60%' and p['values']['driver-change']=='50%'
    assert p['values']['start-label']=='2023-01-01' and p['values']['end-label']=='2026-01-01'
    assert len([n for n in p['values'] if n.startswith('pair-area-axis-')])==3
    changed=contracts.prepare(e,{**v,'driver-data':'2024-01-01,72;2025-01-01,66;2026-01-01,90'},INK)
    assert changed['values']['start-label']=='2024-01-01'
    assert changed['values']['stock-change']=='20%' and changed['values']['driver-change']=='25%'
    with pytest.raises(ValueError,match='observed in both'):contracts.prepare(e,{**v,'driver-data':'2010-01-01,10;2011-01-01,11'},INK)
    assert 'spread_fill'in e['slots']['pair-area-gap']['uses']
    gap=longs.draw(e['slots']['pair-area-gap'],v,INK)[0]
    line=next(n for n in longs.draw(e['slots']['stock-line'],v,INK) if n['tag']=='path')
    import re
    first=lambda n:tuple(map(float,re.match(r'M\s*([\d.-]+)[, ]\s*([\d.-]+)',n['attrs']['d']).groups()))
    assert first(gap)==pytest.approx(first(line))
    assert len(contracts.prepare(e,{**v,'show-gap':'NO'},INK)['motion']['steps'])==3

def test_public_check_names_its_page_and_date_without_a_screenshot(compiled):
    e=entry(compiled,'chapters/claim-vs-checked');v=contracts.example_fill(e)
    with pytest.raises(ValueError,match='page and its ISO date'):contracts.prepare(e,{**v,'found-source':'careers page'},INK)
    p=contracts.prepare(e,v,INK)
    assert p['sources']['found']['kind']=='feed' and p['sources']['found']['feed']=='web_shots'
    assert p['sources']['found']['pageAndDate']=='Careers page / 2026-11-06'
    assert all(n['tag']in('rect','circle','path') for n in p['nodes'])
    assert len(contracts.prepare(e,{**v,'claim-figure':'','found-figure':''},INK)['motion']['steps'])==3

def test_precedent_stops_at_its_real_end_without_forecasting(compiled):
    e=entry(compiled,'charts/then-and-now');v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
    assert p['values']['then-after']=='-80%' and p['values']['now-after']=='-30%'
    assert p['values']['months-after']=='12 months on'
    past=longs.draw(e['slots']['then-line'],v,INK);current=longs.draw(e['slots']['now-line'],v,INK)
    past_end=max(n['attrs']['cx'] for n in past if n['tag']=='circle');now_end=max(n['attrs']['cx'] for n in current if n['tag']=='circle')
    assert now_end<past_end
    with pytest.raises(ValueError,match='never extrapolate'):contracts.prepare(e,{**v,'months-horizon':'24'},INK)
    with pytest.raises(ValueError,match='observed close'):contracts.prepare(e,{**v,'now-event':'2026-01-02'},INK)

def test_existing_tripwires_has_three_dates_and_unchecked_writer_limits():
    item=next(i for i in build_all.catalog_items() if i['key']=='finance/thesis-tripwires')
    assert item['chapterTypes'][0]=='the-watchlist'
    for aspect in ('16x9','9x16'):
        e,_=build_all.compile_plate(item,aspect,INK,2)
        assert 'source'not in e['slots'] and len(e['motion']['steps'])==4
        for i in range(3):
            assert e['slots'][f'by-when-{i+1}']['maxChars']==16
            current=f'current-{i}' if aspect=='16x9' else f'value-{i}-0'
            limit=f'limit-{i}' if aspect=='16x9' else f'value-{i}-1'
            assert e['slots'][current]['source']['kind']=='workbook'
            assert e['slots'][limit]['factCheck']is False and 'fact-check does not check'in e['slots'][limit]['note']
        assert contracts.prepare(e,contracts.example_fill(e),INK)['values']['by-when-1']=='Q1 FY27 print'

def test_question_is_universal_large_centered_and_only_two_ideas(compiled):
    for aspect,maximum in [('16x9',3),('9x16',5)]:
        e=entry(compiled,'cards/question-card',aspect);v=contracts.example_fill(e);p=contracts.prepare(e,v,INK)
        assert set(e['chapterTypes'])==build_all.chapter_types()
        assert set(p['values'])=={'question','kicker'} and not p['nodes']
        assert e['slots']['question']['maxChars']==64
        assert e['typeRoles']['big']['maxLines']==maximum and e['typeRoles']['big']['valign']=='middle'
        assert len(p['motion']['steps'])==2 and p['motion']['steps'][1]['textRange']['text']=='cable'
        assert contracts.prepare(e,{'question':'What does the cable actually do?'},INK)['values']['kicker']==''
        for question in ('This is an answer.','What happened? The answer is cash.','Why 20%?','Why a million dollars?'):
            with pytest.raises(ValueError):contracts.prepare(e,{**v,'question':question},INK)
        with pytest.raises(ValueError,match='occur'):contracts.prepare(e,{**v,'stress-words':'missing word'},INK)

def test_red_flags_publish_both_sources_and_never_draw_a_finding(compiled):
    e=entry(compiled,'chapters/red-flag-checklist');v=contracts.example_fill(e)
    assert 'document sentence'in e['slots']['figure-1']['note']
    assert 'History!accounts_receivable'in e['slots']['figure-2']['note']
    assert e['slots']['figure-2']['source']['pending']is True
    supplied=contracts.prepare(e,{**v,'figure-source-1':'D2.14, D2.16'},INK)
    assert supplied['sources']['figure-1']['kind']=='document' and supplied['sources']['figure-1']['sentences']==['D2.14','D2.16']
    for word in ('FRAUD','fake','cooked'):
        with pytest.raises(ValueError,match='never a fraud finding'):contracts.prepare(e,{**v,'title':word+' CHECK'},INK)

@pytest.mark.parametrize('key',['charts/who-paid','figures/loss-clock'])
def test_new_money_inputs_share_the_zero_guard(key,compiled):
    e=entry(compiled,key);v=contracts.example_fill(e);name='fine-amount' if key.endswith('who-paid') else 'total-1'
    with pytest.raises(ValueError,match='Add m or bn'):contracts.prepare(e,{**v,name:'100'},INK)
