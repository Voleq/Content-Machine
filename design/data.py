"""Pure data renderers. Inputs are manifest regions, workbook slot values and inks.

draw() returns pipeline.series.paint-compatible rect/circle/path nodes.
labels() returns the text/positions computed by the same data calculation.
There are no imports of Pillow, Node, a registry or a file loader here.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal
import math
import re
from . import core,sources

NUMBER=re.compile(r'^(?P<sign>[-+]?)(?P<n>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?P<suffix>bn|mm|[kmbt%]|x|pp|pt|days?|months?)?$',re.I)

def number(value,unit='raw'):
    """Read script notation in the declared source units; reject unit guesses."""
    if type(value) in (int,float):
        if not math.isfinite(value):raise ValueError('Source figures must be finite')
        return float(value)/sources.SCALED_UNITS.get(unit,1)
    if not isinstance(value,str):raise ValueError('A source number must be a written figure')
    text=value.strip().replace('−','-');negative=text.startswith('(') and text.endswith(')')
    if negative:text=text[1:-1]
    sign=''
    if text[:1] in ('+','-'):sign,text=text[0],text[1:]
    if text[:1] in ('$','€','£'):
        currency,text=text[0],text[1:]
        if unit not in ('money','money_m','money_b') or currency!='$':raise ValueError('Currency does not match the declared dollar source unit')
    text=sign+text
    match=NUMBER.fullmatch(text)
    if not match:raise ValueError('Invalid written number: '+value)
    result=float(match['sign']+match['n'].replace(',',''));suffix=(match['suffix'] or '').lower()
    if negative:
        if match['sign']:raise ValueError('Use either parentheses or a sign')
        result=-result
    if suffix in ('k','m','mm','b','bn','t'):
        if unit not in ('money','money_m','money_b','shares','shares_m','quantity_m','count'):raise ValueError('Magnitude suffix needs an explicit source unit')
        multiplier={'k':1e3,'m':1e6,'mm':1e6,'b':1e9,'bn':1e9,'t':1e12}[suffix]
        basis=sources.SCALED_UNITS.get(unit,1)
        result*=multiplier/basis
    elif suffix in ('%','pp','pt') and unit not in ('percent','pp'):
        raise ValueError('A percentage suffix does not match the source unit')
    elif suffix=='x' and unit!='multiple':raise ValueError('A multiple suffix does not match the source unit')
    elif suffix.startswith('day') and unit!='days':raise ValueError('A days suffix does not match the source unit')
    elif suffix.startswith('month') and unit!='months':raise ValueError('A months suffix does not match the source unit')
    if not suffix:result/=sources.SCALED_UNITS.get(unit,1)
    if not math.isfinite(result):raise ValueError('Source figures must be finite')
    return result

def written(value,unit):
    if isinstance(value,str):return value
    s=format(Decimal(str(value)),',f')
    if '.' in s:s=s.rstrip('0').rstrip('.')
    if unit in ('money_m','money'):
        sign='-' if s.startswith('-') else '';s=s.lstrip('-')
        return sign+'$'+s+('m' if unit=='money_m' else '')
    if unit in ('shares_m','quantity_m'):return s+'m'
    if unit=='money_b':return ('-' if s.startswith('-') else '')+'$'+s.lstrip('-')+'bn'
    if unit=='year':return str(int(value))
    if unit in ('percent','pp'):return s+('%' if unit=='percent' else 'pp')
    if unit=='multiple':return s+'x'
    return s

def leaves(value,path=()):
    if isinstance(value,dict):
        for key,item in value.items():yield from leaves(item,(*path,key))
    elif isinstance(value,list):
        for key,item in enumerate(value):yield from leaves(item,(*path,key))
    elif value is not None:yield path,value

FIXED={'unit','units','delta_unit','delta_label','x_unit','window','annual_sessions','domain','x_domain','y_domain','axis_max','event_index','model','field','edges','colour_limit','baseline_day','event_day'}

def unit_for(item,path,value):
    return sources.metadata(item,path)['unit']

def bindings(item,scene):
    """Every variable source observation becomes a script slot, never a default."""
    result={};visible={s['name']:s for s in scene.slots}
    for path,value in leaves(item['example']):
        if path[0] in ('title','takeaway','source') or any(p in FIXED for p in path):continue
        meta=sources.metadata(item,path)
        if meta.get('fixed'):continue
        unit=meta['unit'];scale=meta.get('modelScale',1)
        candidate=core.slug(path[-1]) if isinstance(path[-1],str) else ''
        # Numeric source strings can be whole-unit amounts or written
        # magnitudes. Keep them out of the typeset box: its formatter owns
        # the visible value and unit, regardless of the writer's notation.
        matches=isinstance(value,str) and candidate in visible and visible[candidate]['example']==value
        if path==('period',) or meta.get('sign'):matches=False
        key=candidate if matches else 'input-'+'-'.join(core.slug(p+1 if isinstance(p,int) else p) for p in path)
        if key in result:raise ValueError('Ambiguous source slot '+key)
        note,source=sources.source_note(meta,path,item['example'])
        input_value=value/scale if type(value) in (int,float) else value
        if meta.get('sign')=='outflow-magnitude':input_value=-abs(input_value)
        example=written(input_value,unit)
        note+=' Declared unit: '+unit+'; example '+example+'.'
        result[key]={'path':list(path),'unit':unit,'kind':'number' if type(value) in (int,float) else 'text',
                     'note':note,'source':source,'example':example,'inputOnly':not matches}
        if scale!=1:result[key]['modelScale']=scale
        if meta.get('sign'):result[key]['sign']=meta['sign']
    return result

def native_box(scene):
    boxes=[s['box'] for s in scene.slots if s['scope']=='body']
    # Nodes can extend past a text box (e.g. a plot's axis and arrowheads).
    for n in scene.nodes:
        if n['_scope']!='body':continue
        a=n['attrs']
        if n['tag']=='rect':boxes.append([a['x'],a['y'],a['width'],a['height']])
        elif n['tag']=='circle':boxes.append([a['cx']-a['r'],a['cy']-a['r'],a['r']*2,a['r']*2])
        else:
            pairs=re.findall(r'(-?[\d.]+),(-?[\d.]+)',a['d'])
            if pairs:
                xs,ys=zip(*[(float(x),float(y)) for x,y in pairs]);boxes.append([min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)])
    x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
    return [x,y,max(b[0]+b[2] for b in boxes)-x,max(b[1]+b[3] for b in boxes)-y]

def recipe(item,aspect,scene):
    return {'item':deepcopy(item),'aspect':aspect,'nativeBox':native_box(scene),'bindings':bindings(item,scene),
            'unitLabels':{s['name']:s['example'] for s in scene.slots if s.get('unitLabel')}}

WHOLE_MONEY_CHARTS={
    'revenue-pareto','revenue-treemap','profit-area-mekko','profit-funnel',
    'cash-flow-sankey','investment-payback-path','profit-cash-accumulation',
    'valuation-football-field','dcf-value-duration','maturity-staircase',
    'transaction-network','collection-lag-matrix',
}

def display_places(item,binding):
    """Precision used for monetary/share figures by this plate's drawing."""
    unit=binding['unit'];drawer=item['drawer']
    if unit=='shares':return 0
    if drawer=='stock':
        return min((m.get('places',2) for m in item['definition']['metrics'] if m['unit']==unit),default=2)
    if drawer=='finance':return 2
    if drawer=='investigations':return 2 if unit=='money' and item['legacyId']=='restatement' else 1
    return 0 if item['key'].split('/')[1] in WHOLE_MONEY_CHARTS and unit in ('money','money_m') else 1

def source_number(item,key,binding,raw):
    value=number(raw,binding['unit'])
    if binding['unit'] in ('money','money_m','money_b','shares','shares_m'):
        # Inspect the validated input as well: scaling a non-zero float can
        # underflow to zero before the display-rounding check.
        nonzero=raw!=0 if type(raw) in (int,float) else any(c in '123456789' for c in raw)
        if nonzero and float(f'{value:.{display_places(item,binding)}f}')==0:
            unit=sources.UNIT_LABELS[binding['unit']]
            raise ValueError(f'{key}: {raw!r} is non-zero but would display as zero in {unit}. '
                             'Add m or bn if copied from a filing table in millions or billions (for example 100m).')
    return value

def _scene(region,values,inks):
    spec=region['recipe'];expected=spec['bindings']
    if set(values)!=set(expected):raise ValueError('Missing or unknown workbook input slots')
    fields=deepcopy(spec['item']['example'])
    for key,binding in expected.items():
        value=source_number(spec['item'],key,binding,values[key]) if binding['kind']=='number' else values[key]
        if binding['kind']=='number':
            value*=binding.get('modelScale',1)
            if binding.get('sign')=='outflow-magnitude':value=abs(value)
        if binding['kind']=='number' and value.is_integer():value=int(value)
        if binding['kind']=='text' and (not isinstance(value,str) or not value.strip() or any(ord(c)<32 for c in value)):raise ValueError('Use a short source label')
        if binding['path']==['period']:sources.reporting_label(value)
        target=fields
        for part in binding['path'][:-1]:target=target[part]
        target[binding['path'][-1]]=value
    return core.assemble(spec['item'],spec['aspect'],fields,inks=inks)[0]

def _transform_node(n,source,target):
    sx,sy,sw,sh=source;tx,ty,tw,th=(target[k] for k in ('x','y','w','h'));kx,ky=tw/sw,th/sh
    x=lambda v:tx+(v-sx)*kx
    y=lambda v:ty+(v-sy)*ky
    a=deepcopy(n['attrs'])
    if n['tag']=='rect':a.update(x=x(a['x']),y=y(a['y']),width=a['width']*kx,height=a['height']*ky)
    elif n['tag']=='circle':a.update(cx=x(a['cx']),cy=y(a['cy']),r=a['r']*min(kx,ky))
    else:a['d']=re.sub(r'(-?[\d.]+),(-?[\d.]+)',lambda m:f'{x(float(m[1])):.6f},{y(float(m[2])):.6f}',a['d'])
    if 'stroke-width' in a:a['stroke-width']*=min(kx,ky)
    return {'tag':n['tag'],'attrs':a}

def draw(region,numbers,inks):
    """One pure function for each region recipe: no file/font/image dependencies."""
    core.finite({k:region[k] for k in ('x','y','w','h')})
    if region['w']<=0 or region['h']<=0:raise ValueError('Data region must have a positive size')
    scene=_scene(region,numbers,inks);source=region['recipe']['nativeBox']
    return [_transform_node(n,source,region) for n in scene.nodes if n['_scope']=='body']

def labels(region,numbers,inks):
    """Axis ticks, periods, calculated labels and positions from the same figures."""
    scene=_scene(region,numbers,inks);sx,sy,sw,sh=region['recipe']['nativeBox'];kx,ky=region['w']/sw,region['h']/sh
    result=[]
    for s in scene.slots:
        if s['scope']!='body':continue
        x,y,w,h=s['box']
        result.append({'slot':s['name'],'text':s['example'],'box':[region['x']+(x-sx)*kx,region['y']+(y-sy)*ky,w*kx,h*ky]})
    return result
