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
from . import core

NUMBER=re.compile(r'^(?P<sign>[-+]?)(?P<n>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?P<suffix>bn|mm|[kmbt%]|x|pp|pt|days?|months?)?$',re.I)

def number(value,unit='raw'):
    """Read script notation in the declared source units; reject unit guesses."""
    if type(value) in (int,float):
        if not math.isfinite(value):raise ValueError('Source figures must be finite')
        return float(value)
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
        if unit not in ('money','money_m','money_b','shares_m'):raise ValueError('Magnitude suffix needs an explicit source unit')
        multiplier={'k':1e3,'m':1e6,'mm':1e6,'b':1e9,'bn':1e9,'t':1e12}[suffix]
        basis=1e6 if unit in ('money_m','shares_m') else 1e9 if unit=='money_b' else 1
        result*=multiplier/basis
    elif suffix in ('%','pp','pt') and unit not in ('percent','pp'):
        raise ValueError('A percentage suffix does not match the source unit')
    elif suffix=='x' and unit!='multiple':raise ValueError('A multiple suffix does not match the source unit')
    elif suffix.startswith('day') and unit!='days':raise ValueError('A days suffix does not match the source unit')
    elif suffix.startswith('month') and unit!='months':raise ValueError('A months suffix does not match the source unit')
    if not math.isfinite(result):raise ValueError('Source figures must be finite')
    return result

def written(value,unit):
    if isinstance(value,str):return value
    s=format(Decimal(str(value)),',f')
    if '.' in s:s=s.rstrip('0').rstrip('.')
    if unit in ('money_m','money'):
        sign='-' if s.startswith('-') else '';s=s.lstrip('-')
        return sign+'$'+s+('m' if unit=='money_m' else '')
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

FIXED={'unit','delta_unit','x_unit','window','annual_sessions','domain','x_domain','y_domain','axis_max','event_index','model','field','edges'}

def unit_for(item,path,value):
    if not isinstance(value,(int,float)):return 'text'
    name=str(path[-1]);definition=item['definition'];fields=item['example']
    if any(p in ('years','year') for p in path) and 1900<=value<=9999:return 'year'
    if name.endswith(('_pct','_percent')) or name in ('margin_pct','borrow_pct'):return 'percent'
    if item['drawer']=='stock':
        for metric in definition.get('metrics',[]):
            if metric.get('expr')==name:return metric['unit']
    if name.endswith('_m'):return 'money_m'
    if name.endswith(('_days','_day')):return 'days'
    if name.endswith('_months'):return 'months'
    if item['drawer'] in ('finance','investigations','research'):
        if item['drawer']=='research':
            hint=definition.get('fields',{}).get(name,{})
            label=hint.get('label','')+' '+hint.get('instruction','')
            if '$m' in label or '$m' in str(fields.get('period','')):return 'money_m'
        elif '$m' in str(fields.get('period','')) and not any(t in name for t in ('share','growth','margin','rate','index','price','days','month','percent','pct')):return 'money_m'
    data=fields.get('data',{})
    if isinstance(data,dict):
        unit=data.get('unit')
        if unit=='$m':return 'money_m'
        if unit=='$':return 'money'
        if unit=='%':return 'percent'
    return 'raw'

def bindings(item,scene):
    """Every variable source observation becomes a script slot, never a default."""
    result={};visible={s['name']:s for s in scene.slots}
    for path,value in leaves(item['example']):
        if path[0] in ('title','takeaway','source') or any(p in FIXED for p in path):continue
        unit=unit_for(item,path,value)
        candidate=core.slug(path[-1]) if isinstance(path[-1],str) else ''
        if candidate in visible:
            try:matches=visible[candidate]['example']==value if isinstance(value,str) else math.isclose(number(visible[candidate]['example'],unit),value,rel_tol=1e-9,abs_tol=1e-9)
            except ValueError:matches=False
        else:matches=False
        key=candidate if matches else 'input-'+'-'.join(core.slug(p+1 if isinstance(p,int) else p) for p in path)
        if key in result:raise ValueError('Ambiguous source slot '+key)
        path_words=' / '.join(str(p+1 if isinstance(p,int) else p).replace('_',' ') for p in path)
        note=f'Workbook: {path_words}; use the period identified by this plate. Source unit: {unit}; write a figure such as {written(value,unit)}.'
        result[key]={'path':list(path),'unit':unit,'kind':'number' if type(value) in (int,float) else 'text',
                     'note':note,'example':written(value,unit),'inputOnly':not matches}
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
    return {'item':deepcopy(item),'aspect':aspect,'nativeBox':native_box(scene),'bindings':bindings(item,scene)}

def _scene(region,values,inks):
    spec=region['recipe'];expected=spec['bindings']
    if set(values)!=set(expected):raise ValueError('Missing or unknown workbook input slots')
    fields=deepcopy(spec['item']['example'])
    for key,binding in expected.items():
        value=number(values[key],binding['unit']) if binding['kind']=='number' else values[key]
        if binding['kind']=='number' and value.is_integer():value=int(value)
        if binding['kind']=='text' and (not isinstance(value,str) or not value.strip() or any(ord(c)<32 for c in value)):raise ValueError('Use a short source label')
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
