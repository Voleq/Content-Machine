"""Round 3 authoring and pure fill/draw contract. Never registers with the bot."""
from __future__ import annotations
from copy import deepcopy
import csv
from datetime import date,datetime,time,timezone
from io import StringIO
from decimal import Decimal
import math
import re
import calendar
from . import core,data,sources
from .drawings import long_series

STYLE={
    'headline':('Archivo Narrow',64,700),'big':('Courier Prime',124,700),
    'label':('Courier Prime',32,400),'caption':('Archivo Narrow',36,400),
    'value':('Courier Prime',60,700),'callout':('Archivo Narrow',48,700),
    'detail':('Archivo Narrow',32,400),'colHead':('Courier Prime',30,700),
    'unit':('Courier Prime',28,400),'legend':('Courier Prime',30,400),
    'kicker':('Courier Prime',30,400),'source':('Courier Prime',30,400),
    'date':('Courier Prime',30,400),'body':('Courier Prime',36,400),
}
MOVES={'appear','clip-in','count-up','line-draw','bars-grow','highlight','pen-circle','zoom-to-slot','clock-run'}
MONEY_FIELDS={'revenue','gross_profit','operating_income','ebitda','net_income','operating_cf','capex','fcf','sbc','dividends_paid','buybacks','cash','total_debt','net_debt','total_equity','total_assets','invested_capital','accounts_receivable','revenue_consensus'}
RATE_FIELDS={'gross_margin','operating_margin','net_margin','fcf_margin','sbc_pct_rev','roic','roe','shares_yoy'}

def workbook_unit(field):
    if field in MONEY_FIELDS:return 'money_m'
    if field=='diluted_shares':return 'shares_m'
    if field in RATE_FIELDS:return 'percent'
    if field in ('eps','eps_street','eps_consensus','fcf_ps','bvps'):return 'money'
    if field=='net_debt_ebitda':return 'multiple'
    if field=='period_end':return 'date'
    if field in ('fiscal_year','fiscal_quarter'):return 'count'
    raise ValueError('Unknown workbook result field '+field)

def check(ok,message):
    if not ok:raise ValueError(message)

def field_specs(item,aspect,variant=None):
    fields={n:deepcopy(s) for n,s in item['fields'].items() if aspect not in s.get('omitAspects',[])}
    for spec in fields.values():
        if aspect in spec.get('defaultsByAspect',{}):spec['default']=spec['defaultsByAspect'][aspect]
    if item['model']=='mechanism' and variant:
        for name in list(fields):
            match=re.fullmatch(r'(step|detail|arrow)-(\d)',name)
            if match and (int(match[2])>variant['steps'] or match[1]=='arrow' and int(match[2])==variant['steps']):fields.pop(name)
            elif name=='loop-label' and not variant['loop']:fields.pop(name)
    return fields

def unit_for(spec,raw):
    if spec.get('unitFromField') and raw.get(spec['unitFromField']):return workbook_unit(raw[spec['unitFromField']])
    return raw.get(spec['unitFrom'],spec['unit']) if spec.get('unitFrom') else spec['unit']

def number(item,name,spec,value,raw):
    unit=unit_for(spec,raw)
    result=data.source_number(item,name,{'unit':unit,'displayPlaces':spec.get('places',2)},value)
    if unit=='count':check(result.is_integer(),name+' must be a whole count')
    return result

def fmt(value,unit,places=2):
    if unit=='count':return str(int(value))
    s=f'{abs(value):,.{places}f}';s=s.rstrip('0').rstrip('.') if places else s
    sign='-' if value<0 else ''
    if unit in ('money','money_m','money_b'):return sign+'$'+s+{'money':'','money_m':'m','money_b':'bn'}[unit]
    return sign+s+{'percent':'%','multiple':'x','shares_m':'m','shares':'','count':'','index':''}.get(unit,'')

def moment(value):
    check(isinstance(value,str) and value.strip(),'A dated observation needs a date or time')
    value=value.strip()
    if re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?',value):
        t=time.fromisoformat('0'+value if value.index(':')==1 else value)
        d=datetime(2000,1,1,t.hour,t.minute,t.second)
    else:
        if re.fullmatch(r'\d{4}-\d{2}',value):value+='-01'
        try:d=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            for pattern in ('%d %b %Y','%d %B %Y','%b %d, %Y'):
                try:d=datetime.strptime(value,pattern);break
                except ValueError:pass
            else:raise ValueError('Use an ISO date or a document time HH:MM[:SS]')
    if d.tzinfo:d=d.astimezone(timezone.utc).replace(tzinfo=None)
    return (d-datetime(1970,1,1)).total_seconds()

def rows(raw):
    if isinstance(raw,list):return deepcopy(raw)
    return list(csv.reader(StringIO(raw.replace(';','\n')))) if raw else []

def normalize(item,aspect,values,variant=None):
    specs=field_specs(item,aspect,variant);expected={n for n,s in specs.items() if not s.get('computed')}
    check(not set(values)-expected,'Unknown or computed writer slot: '+', '.join(sorted(set(values)-expected)))
    raw={n:s.get('default','') for n,s in specs.items() if n in expected and ('default'in s or s.get('optional'))}
    raw.update(deepcopy(values));check(not expected-set(raw),'Missing required writer slots: '+', '.join(sorted(expected-set(raw))))
    visible={};numbers={}
    for name,value in raw.items():
        spec=specs[name]
        if spec.get('table') and isinstance(value,list):continue
        unit=unit_for(spec,raw)
        if value and spec.get('unitFromField'):check(bool(raw.get(spec['unitFromField'])),name+' needs its actual workbook field_key')
        if type(value) in (int,float) and unit in ('money','money_m','money_b','shares_m','shares','percent','multiple','count','index'):
            numbers[name]=number(item,name,spec,value,raw);visible[name]=fmt(numbers[name],unit,spec.get('places',2));continue
        check(isinstance(value,str),name+' must be written as a script string')
        check(value==value.strip() and not any(ord(c)<32 or c in '|]' for c in value),'Invalid script text in '+name)
        check(bool(value) or spec.get('optional'),name+' must not be empty')
        if not value:visible[name]='';continue
        if unit in ('money','money_m','money_b','shares_m','shares','percent','multiple','count','index'):
            check(len(value)<=64,name+' has an excessive source value')
            numbers[name]=number(item,name,spec,value,raw);visible[name]=fmt(numbers[name],unit,spec.get('places',2 if unit!='count' else 0))
        else:
            check(len(value)<=spec.get('maxChars',64),name+' exceeds its character limit')
            visible[name]=value
        if 'enum'in spec:check(value in spec['enum'],name+' must be one of '+', '.join(spec['enum']))
        if spec.get('pattern'):check(re.fullmatch(spec['pattern'],value),name+' needs a document sentence such as D2.14')
    return raw,visible,numbers

class Canvas(core.Scene):
    def __init__(self,item,aspect,raw,values,numbers,inks=None,variant=None):
        self.item=item;self.aspect=aspect;self.portrait=aspect=='9x16';self.key=item['key']
        self.w,self.h=(1080,1920) if self.portrait else (1920,1080)
        self.ink={name:name for name in core.INK_NAMES};self.ink.update(inks or {})
        self.raw=raw;self.values=values;self.numbers=numbers;self.specs=field_specs(item,aspect,variant);self.variant=variant
        self.slots=[];self.nodes=[];self.regions=[];self.chart_marks=[];self.stages={};self.primitives=[]
        self.scope='frame';self.filled=True;self.ground='paper';self.region_name=None;self.rect(0,0,self.w,self.h,'ground');self.scope='body'

    def emit(self,item):
        item['_scope']=self.scope
        if self.region_name:item['_region']=self.region_name
        self.nodes.append(item)

    def field(self,name,x,y,w,h,*,value=None,role=None,colour='structure',align='left',unit='text',note=None):
        spec=self.specs.get(name,{'role':role or 'label','unit':unit,'maxChars':max(16,len(str(value or ''))),'computed':True,
                                  'note':note or 'Computed label from the declared data; not an independent writer input.','factCheck':False})
        role=role or spec['role'];family,size,weight=STYLE[role]
        if self.item['model']=='question' and role=='big':family,size,weight='Archivo Narrow',160 if self.portrait else 200,700
        if self.portrait and role=='big' and self.item['model']!='question':size=104
        if self.portrait:size=max(size,32)
        self.text(name,self.values.get(name,'') if value is None else value,x,y,w,h,size=size,kind='sans' if family=='Archivo Narrow' else 'mono-bold' if weight==700 else 'mono',weight=weight,colour=colour,align=align,minimum=30 if self.portrait else 24)
        self.slots[-1].update(role=role,spec=deepcopy(spec))
        maximum=spec.get('maxLinesByAspect',{}).get(self.aspect,spec.get('maxLines'))
        if maximum:self.slots[-1]['maxLines']=maximum

    def title(self):self.field('title',96,100 if self.portrait else 72,self.w-192,170 if self.portrait else 145)

    def region(self,name,box,uses=(),children=()):
        self.region_name=name;self.regions.append({'name':name,'box':list(box),'uses':list(uses),**({'children':list(children),'composite':True} if children else {})})

    def add_nodes(self,nodes):
        for n in nodes:self.emit(deepcopy(n))

    def require(self,name):
        check(name in self.raw and self.raw[name] is not None and self.raw[name]!='',name+' is required for the active row');return self.values[name]

    def num(self,name):
        self.require(name);return self.numbers[name]

    def count(self,name,low,high):
        n=int(self.num(name));check(low<=n<=high,f'{name} must be between {low} and {high}');return n

def price_series(p,name,value_unit='money',nonnegative=True):
    result=[]
    for i,row in enumerate(rows(p.raw.get(name,''))):
        if isinstance(row,dict):row=[row.get('date'),row.get('price',row.get('close'))]
        check(len(row)==2,name+' needs date,price rows separated by semicolons')
        stamp=moment(row[0]);v=number(p.item,f'{name} row {i+1}',{'unit':value_unit},str(row[1]),p.raw)
        if nonnegative:check(v>=0,'Prices must not be negative')
        result.append((stamp,v))
    check(not result or len(result)>=2,'A price line needs at least two observations')
    check(all(a[0]<b[0] for a,b in zip(result,result[1:])),name+' dates must be strictly increasing')
    return result

def plot(p,name,box,series,*,xdomain=None,ydomain=None,xunit='date',yunit='money',parts=None,gap=False):
    xs=[x for _,points in series for x,_ in points];ys=[y for _,points in series for _,y in points]
    x0,x1=xdomain or (min(xs),max(xs));y0,y1=ydomain or (min(ys),max(ys))
    if y0==y1:y0=max(0,y0-1);y1+=1
    check(x1>x0 and y1>y0,'Plot needs a nonempty axis')
    x,y,w,h=box;p.region(name,box,('line_path','spread_fill') if gap else ('line_path',),[name+'-furniture',*parts,*([name+'-gap'] if gap else [])] if parts else [])
    if parts:p.region(name+'-furniture',box,())
    p.line([(x,y),(x,y+h),(x+w,y+h)],'axis',2)
    for i in range(3):
        v=y0+(y1-y0)*i/2;py=y+h-h*i/2
        if i:p.line([(x,py),(x+w,py)],'rule',1)
        p.field(name+'-axis-'+str(i),max(8,x-138),py-20,126,42,value=fmt(v,yunit,2 if yunit=='money' else 1),role='label',unit=yunit,align='right')
    for i in range(3):
        v=x0+(x1-x0)*i/2
        label=datetime.fromtimestamp(v,timezone.utc).strftime('%H:%M' if xunit=='time' else '%Y-%m') if xunit!='count' else f'{v:.1f}'.rstrip('0').rstrip('.')
        p.field(name+'-date-'+str(i),x+w*i/2-70,y+h+15,140,44,value=label,role='label',unit='date' if xunit!='count' else 'count',align='center')
    if gap:
        check(len(series)==2 and [q[0] for q in series[0][1]]==[q[0] for q in series[1][1]],'A gap needs two aligned series')
        p.region(name+'-gap',box,('spread_fill',))
        columns=[{'anchorX':x+(vx-x0)/(x1-x0)*w} for vx,_ in series[0][1]]
        # spread_fill includes zero in its native extent. Translate both
        # series to a zero-based domain so it uses the lines' exact scale.
        result=core.native_series.spread_fill(dict(zip(('x','y','w','h'),box)),[v-y0 for _,v in series[0][1]],[v-y0 for _,v in series[1][1]],p.ink,columns=columns,min=0,max=y1-y0)
        p.series_nodes('spread_fill',result['nodes'])
    for i,(colour,points) in enumerate(series):
        if parts:p.region(parts[i],box,('line_path',))
        columns=[{'anchorX':x+(vx-x0)/(x1-x0)*w} for vx,_ in points]
        result=core.native_series.line_path(dict(zip(('x','y','w','h'),box)),[v for _,v in points],p.ink,columns=columns,min=y0,max=y1,zero=False,tone=colour,weight=6)
        p.series_nodes('line_path',result['nodes'])
    return lambda vx,vy:(x+(vx-x0)/(x1-x0)*w,y+h-(vy-y0)/(y1-y0)*h)

RENDER={}

def render_cast(p):
    p.title();count=p.count('player-count',1,6);cols=2 if p.portrait else 3
    w=(p.w-192-(cols-1)*28)/cols;h=360 if p.portrait else 286
    p.region('cast-area',[96,330 if p.portrait else 275,p.w-192,(3 if p.portrait else 2)*(h+28)],())
    for i in range(1,7):
        x=96+(i-1)%cols*(w+28);y=(330 if p.portrait else 275)+(i-1)//cols*(h+28)
        if i<=count:
            p.require(f'name-{i}');p.require(f'role-{i}');p.require(f'status-{i}');p.card(x,y,w,h)
        p.field(f'name-{i}',x+22,y+20,w-44,130 if p.portrait else 110,value=p.values.get(f'name-{i}','') if i<=count else '')
        p.field(f'role-{i}',x+22,y+(160 if p.portrait else 140),w-44,88 if p.portrait else 64,value=p.values.get(f'role-{i}','') if i<=count else '')
        p.field(f'status-{i}',x+22,y+h-74,w-44,58,value=p.values.get(f'status-{i}','') if i<=count else '',colour='quiet' if p.raw.get(f'status-{i}') in ('NO STATUS','NOT CHARGED') else 'attention')

def render_collapse(p):
    p.title();count=p.count('event-count',0,6);start=moment(p.require('axis-start'));end=moment(p.require('axis-end'))
    check(end>start,'Timeline end must follow its start');prices=price_series(p,'price-data')
    box=[232,390,706,470] if p.portrait else [224,280,1560,320]
    p.region('fall-area',box,('line_path','event_pins'),['fall-line',*[f'pin-area-{i}' for i in range(1,count+1)]])
    if prices:
        check(p.raw['value-unit']=='money','A price feed uses per-share dollars, not total company value')
        check(start<=prices[0][0] and prices[-1][0]<=end,'Price observations must be within the dated timeline')
        top=max(v for _,v in prices);bottom=prices[-1][1]
        xy=plot(p,'fall-line',box,[('subject',prices)],xdomain=(start,end),xunit='time' if p.raw['clock-unit']=='MINUTES' else 'date')
    else:
        p.region('fall-line',box,());x,y,w,h=box;p.line([(x,y+h/2),(x+w,y+h/2)],'axis',3)
        xy=lambda t,v:(x+(t-start)/(end-start)*w,y+h/2)
        top=p.num('top');bottom=p.num('bottom')
        for i in range(3):
            p.field('fall-line-axis-'+str(i),max(8,x-138),y+h-h*i/2-20,126,42,value='',role='label',unit='money',align='right')
            stamp=start+(end-start)*i/2;label=datetime.fromtimestamp(stamp,timezone.utc).strftime('%H:%M' if p.raw['clock-unit']=='MINUTES' else '%Y-%m')
            p.field('fall-line-date-'+str(i),x+w*i/2-70,y+h/2+15,140,44,value=label,role='label',unit='date',align='center')
    check(top>0 and 0<=bottom<=top,'Collapse values need a positive top and a bottom between zero and the top')
    p.field('clock-unit',96,285 if p.portrait else 220,p.w-192,48,colour='quiet')
    pins=[]
    for i in range(1,7):
        x0=96+((i-1)%(2 if p.portrait else 3))*(458 if p.portrait else 584)
        y0=(1030 if p.portrait else 690)+((i-1)//(2 if p.portrait else 3))*(148 if p.portrait else 94)
        active=i<=count
        if active:
            p.require(f'event-{i}');t=moment(p.require(f'when-{i}'));check(start<=t<=end,'Every event must lie on the dated axis')
            if prices:
                left=max((q for q in prices if q[0]<=t),default=prices[0]);right=min((q for q in prices if q[0]>=t),default=prices[-1])
                check(prices[0][0]<=t<=prices[-1][0],'An event pin needs an observed price interval; use an axis-only timeline otherwise')
                v=left[1] if right[0]==left[0] else left[1]+(right[1]-left[1])*(t-left[0])/(right[0]-left[0]);point=xy(t,v)
            else:point=xy(t,0)
            pins.append(point);p.region(f'pin-area-{i}',[point[0]-24,point[1]-90,48,90],('event_pins',));p.add_nodes(long_series.event_pins(dict(zip(('x','y','w','h'),box)),[point],p.ink))
            p.field(f'pin-{i}',point[0]-16,point[1]-82,32,36,value=str(i),role='label',unit='count',align='center')
        p.field(f'event-{i}',x0+46,y0,388 if p.portrait else 510,74 if p.portrait else 42,value=p.values.get(f'event-{i}','') if active else '')
        p.field(f'when-{i}',x0+46,y0+(78 if p.portrait else 44),388 if p.portrait else 510,44,value=p.values.get(f'when-{i}','') if active else '',colour='quiet')
    unit=p.raw['value-unit'];p.values.update(top=fmt(top,unit),bottom=fmt(bottom,unit),drop=fmt((bottom/top-1)*100,'percent',1))
    for i,name in enumerate(('top','bottom','drop')):
        x=96+i*(p.w-192)/3;y=1590 if p.portrait else 900
        p.field(name+'-label',x,y,(p.w-192)/3-20,44,value=name.upper(),role='label')
        p.field(name,x,y+55,(p.w-192)/3-20,150 if name=='drop' and p.portrait else 110)

def mechanism_boxes(p):
    n=p.variant['steps'];boxes=[]
    for i in range(n):
        if p.portrait:
            row=i//2;col=i%2 if row%2==0 else 1-i%2;boxes.append([96+col*466,350+row*400,422,326])
        else:boxes.append([96+i*(1728/n),350,1728/n-34,338])
    return boxes

def render_mechanism(p):
    p.title();boxes=mechanism_boxes(p);n=len(boxes);stop=p.count('stop-at',1,n)
    p.region('mechanism-area',[96,300,p.w-192,1280 if p.portrait else 530],())
    for i,(x,y,w,h) in enumerate(boxes,1):
        p.require(f'step-{i}');p.require(f'detail-{i}');p.card(x,y,w,h)
        p.field(f'ordinal-{i}',x+18,y+14,w-36,45,value=str(i),role='kicker',unit='count',colour='quiet')
        p.field(f'step-{i}',x+18,y+65,w-36,100)
        p.field(f'detail-{i}',x+18,y+180,w-36,120)
        if i<n:
            nx,ny,nw,nh=boxes[i]
            if ny==y:points=[(x+w,y+h/2),(nx if nx>x else nx+nw,ny+nh/2)]
            else:points=[(x+w/2,y+h),(nx+nw/2,ny)]
            p.line(points,'axis',3,arrow=True)
            p.field(f'arrow-{i}',min(x,nx)+20,(y+h+24 if ny!=y else y-80),max(w,nw)-40,70)
    if p.variant['loop']:
        first=boxes[0];last=boxes[-1];ly=(boxes[-1][1]+boxes[-1][3]+76)
        p.line([(last[0]+last[2]/2,last[1]+last[3]),(last[0]+last[2]/2,ly),(first[0]-36,ly),(first[0]-36,first[1]+first[3]/2),(first[0],first[1]+first[3]/2)],'subject',4,arrow=True)
        p.field('loop-label',96,ly+10,p.w-192,60,align='center')
    selected=boxes[stop-1];p.region('stop-mark',[selected[0]-9,selected[1]-9,selected[2]+18,selected[3]+18],())
    x,y,w,h=selected;p.line([(x-9,y-9),(x+w+9,y-9),(x+w+9,y+h+9),(x-9,y+h+9),(x-9,y-9)],'attention',5)
    p.field('stop-label',96,1690 if p.portrait else 895,p.w-192,110,colour='attention')

def render_bill(p):
    p.title();n=p.count('party-count',1,6);ordered=sorted(range(1,n+1),key=lambda i:p.num(f'amount-{i}'),reverse=True)
    check(all(p.num(f'amount-{i}')>=0 for i in ordered) and p.num('fine-amount')>=0,'Losses and fines must be nonnegative')
    if any(p.raw.get(f'kind-{i}')=='PAPER LOSS' for i in ordered):
        for i in ordered:
            if p.raw.get(f'kind-{i}')=='PAPER LOSS':check('paper' in p.raw.get(f'note-{i}','').lower(),'Label a market-value loss as a paper loss')
    rowh=176 if p.portrait else 78;top=350 if p.portrait else 275
    box=[390 if p.portrait else 700,top,365 if p.portrait else 820,rowh*(n+1)]
    rowspec=[{'y':top+i*rowh,'h':rowh-18} for i in range(n+1)];amounts=[p.num(f'amount-{i}') for i in ordered]+[p.num('fine-amount')]
    maximum=max(amounts) or 1
    p.region('bill-area',box,('row_bars',));result=core.native_series.row_bars(dict(zip(('x','y','w','h'),box)),rowspec,amounts,p.ink,accent=n,min=0,max=maximum)
    p.series_nodes('row_bars',result['nodes'][:-1])
    p.region('fine-bar',[box[0],top+n*rowh,box[2],rowh-18],('row_bars',));p.series_nodes('row_bars',result['nodes'][-1:])
    for row,i in enumerate(ordered):
        y=top+row*rowh;p.require(f'party-{i}');p.field(f'party-{i}',96,y,274 if p.portrait else 560,78 if p.portrait else 44)
        p.field(f'note-{i}',96,y+82 if p.portrait else y+40,274 if p.portrait else 560,74 if p.portrait else 36,colour='quiet')
        p.field(f'amount-{i}',780 if p.portrait else 1544,y+20,204 if p.portrait else 280,90 if p.portrait else 62,align='right')
    y=top+n*rowh;p.field('fine-label',96,y,274 if p.portrait else 560,74 if p.portrait else 44,colour='attention');p.field('fine-amount',780 if p.portrait else 1544,y+20,204 if p.portrait else 280,90 if p.portrait else 62,align='right',colour='attention')
    p.values['ratio']=fmt(max(amounts[:-1])/amounts[-1],'multiple',1) if amounts[-1] else 'N/A'
    p.field('ratio',96,1690 if p.portrait else 915,p.w-192,140,colour='attention')
    p.field('bill-unit',96,290 if p.portrait else 210,p.w-192,42,value='$m / ONE SHARED SCALE',role='unit')

def render_ended(p):
    p.title();n=p.count('row-count',1,5);rowh=244 if p.portrait else 116;top=360 if p.portrait else 320
    box=[424 if p.portrait else 750,top,514 if p.portrait else 620,rowh*n];stage_rows=[]
    for j in range(1,5):
        p.field(f'ladder-{j}',box[0]+(j-1)*box[2]/3-74,top-70,148,62,align='center')
    for i in range(1,n+1):
        y=top+(i-1)*rowh;p.require(f'name-{i}');p.require(f'role-{i}');p.require(f'outcome-{i}')
        stage=p.count(f'stage-{i}',0,4);tried=p.raw[f'tried-{i}']=='YES'
        check(stage!=3 or tried,'A TRIED stage must be supported by a recorded trial')
        stage_rows.append({'stage':stage,'tried':tried})
        p.field(f'name-{i}',96,y+12,300 if p.portrait else 610,66)
        p.field(f'role-{i}',96,y+83 if p.portrait else y+68,300 if p.portrait else 610,66 if p.portrait else 40,colour='quiet')
        p.field(f'outcome-{i}',96 if p.portrait else 1430,y+164 if p.portrait else y+14,888 if p.portrait else 394,78)
    p.region('ladder-area',box,('stage_ladder',),[f'ladder-row-{i}' for i in range(1,n+1)])
    for i,row in enumerate(stage_rows,1):
        rb=[box[0],top+(i-1)*rowh,box[2],rowh];p.region(f'ladder-row-{i}',rb,('stage_ladder',));p.add_nodes(long_series.stage_ladder(dict(zip(('x','y','w','h'),rb)),[row],p.ink))
    p.field('what-changed',96,1670 if p.portrait else 944,p.w-192,130 if p.portrait else 90)

def render_clock(p):
    start=moment(p.require('clock-start'));end=moment(p.require('clock-end'));check(end>start,'Clock end must follow its start')
    active=[i for i in range(1,5) if p.raw.get(f'total-{i}')]
    check(active and active==list(range(1,len(active)+1)),'Clock checkpoints must be contiguous, with a documented final figure')
    previous=start;last_total=0
    for i in active:
        if not p.raw.get(f'at-{i}') and i==active[-1]:p.raw[f'at-{i}']=p.raw['clock-end'];p.values[f'at-{i}']=p.raw['clock-end']
        t=moment(p.require(f'at-{i}'));v=p.num(f'total-{i}');check(previous<t<=end,'Checkpoint times must increase within the document interval');check(v>=last_total,'Running totals cannot decrease')
        previous=t;last_total=v
    check(previous==end,'The final checkpoint must be the documented end time')
    if len(active)==1:
        minutes=(end-start)/60;duration=fmt(minutes,'count',2)
        check(re.search(r'\bover\s+'+re.escape(duration)+r'\s+minutes\b',p.raw['caption'],re.I),'With only a final total, caption must say over '+duration+' minutes; do not invent intermediate losses')
    p.field('kicker',96,120 if p.portrait else 85,p.w-192,64)
    box=[210,290,660,660] if p.portrait else [170,250,570,570]
    p.region('clock-area',box,('clock_face',));p.add_nodes(long_series.clock_face(dict(zip(('x','y','w','h'),box)),p.raw['clock-end'],p.ink))
    p.field('clock-start',96,1020 if p.portrait else 850,390 if p.portrait else 310,100)
    p.field('clock-end',594 if p.portrait else 540,1020 if p.portrait else 850,390 if p.portrait else 310,100,align='right')
    p.field('total-label',96 if p.portrait else 930,1180 if p.portrait else 290,888 if p.portrait else 850,70)
    unit=p.raw['total-unit'];p.field('live-total',96 if p.portrait else 930,1260 if p.portrait else 385,888 if p.portrait else 850,200,value=fmt(last_total,unit),role='big',unit=unit)
    for i in range(1,5):
        x=96+(i-1)*(222 if p.portrait else 212);y=1530 if p.portrait else 660
        if not p.portrait:x+=820
        p.field(f'at-{i}',x,y,204,48,value=p.values.get(f'at-{i}','') if i in active else '',colour='quiet');p.field(f'total-{i}',x,y+62,204,88,value=p.values.get(f'total-{i}','') if i in active else '')
    p.field('caption',96,1740 if p.portrait else 970,p.w-192,96)

def render_toy(p):
    p.title();n=p.count('row-count',1,5);p.field('tag',96,280 if p.portrait else 218,p.w-192,48,colour='attention')
    p.field('head-step',96,350 if p.portrait else 282,870 if p.portrait else 800,50)
    if not p.portrait:
        p.field('head-amount',1010,282,320,50,align='right');p.field('head-total',1390,282,434,50,align='right')
    else:
        p.field('head-amount',96,405,380,50);p.field('head-total',550,405,434,50,align='right')
    previous=Decimal('0');rowh=220 if p.portrait else 102
    p.region('ledger-area',[96,480 if p.portrait else 350,p.w-192,rowh*n],())
    for i in range(1,6):
        y=(480 if p.portrait else 350)+(i-1)*rowh
        if i<=n:
            p.require(f'step-{i}');amount=p.num(f'amount-{i}');total=p.num(f'total-{i}')
            check(previous+Decimal(str(amount))==Decimal(str(total)),f'total-{i} does not add up: previous total plus amount-{i} must equal total-{i}')
            previous=Decimal(str(total));p.line([(96,y-12),(p.w-96,y-12)],'rule',2)
        for name,x,w,dy,align in ((f'step-{i}',96,888 if p.portrait else 840,12,'left'),(f'amount-{i}',96 if p.portrait else 1000,380 if p.portrait else 330,112 if p.portrait else 8,'left' if p.portrait else 'right'),(f'total-{i}',550 if p.portrait else 1380,434,112 if p.portrait else 8,'right')):
            p.field(name,x,y+dy,w,90,value=p.values.get(name,'') if i<=n else '',align=align,colour='subject' if name.startswith('total') else 'structure')
    p.field('outcome',96,1720 if p.portrait else 940,p.w-192,120)

def marked_lines(body,selected,width,size):
    """Character ranges on the fixed-width Courier body, without font I/O."""
    start=body.find(selected);check(start>=0,'The marked sentence must be copied exactly from body')
    end=start+len(selected);advance=size*.6;lines=[];line=[];used=0
    for word in re.finditer(r'\S+',body):
        length=len(word[0])*advance
        if line and used+advance+length>width-4:lines.append(line);line=[];used=0
        line.append((word.start(),word.end(),used+(advance if used else 0)));used+=(advance if used else 0)+length
    if line:lines.append(line)
    spans=[]
    for j,line in enumerate(lines):
        portions=[(x+max(0,start-a)*advance,x+min(b-a,end-a)*advance) for a,b,x in line if b>start and a<end]
        if portions:spans.append((min(a for a,b in portions),j*size*1.18,max(b for a,b in portions)-min(a for a,b in portions),size*1.14))
    return spans

def render_press(p):
    p.field('source',128,90,1050,64,colour='quiet');p.field('date',1240,90,552,64,align='right',colour='quiet')
    p.field('headline',128,220,1664,220);p.field('body',128,510,1664,350,colour='quiet')
    body=p.require('body');selected=p.raw.get('marked-sentence') or re.split(r'(?<=[.!?])\s+',body,maxsplit=1)[0]
    spans=marked_lines(body,selected,1664,STYLE['body'][1])
    p.region('mark-area',[128,510,1664,350],())
    for x,y,w,h in spans:p.rect(128+x,510+y,w,h,'subject4','structure',1)
    p.field('caption',128,960,1664,70)

def render_flags(p):
    p.title();rowh=256 if p.portrait else 128;top=355 if p.portrait else 270
    check(not any(re.search(r'\b(fraud|fake|cooked)\b',v,re.I) for n,v in p.values.items() if not p.specs[n].get('inputOnly')),'A red flag is a reason to read further, never a fraud finding')
    p.region('checks-area',[96,top,p.w-192,rowh*5],())
    for i in range(1,6):
        y=top+(i-1)*rowh;p.require(f'check-{i}');p.require(f'figure-{i}');p.require(f'mark-{i}')
        for n in (f'check-{i}',f'note-{i}'):
            check(not re.search(r'\b(fraud|fake|cooked)\b',p.raw.get(n,''),re.I),'A red flag is a reason to read further, never a fraud finding')
        p.line([(96,y),(p.w-96,y)],'rule',2)
        p.field(f'check-{i}',96,y+18,888 if p.portrait else 590,72)
        p.field(f'figure-{i}',96 if p.portrait else 750,y+103 if p.portrait else y+15,410 if p.portrait else 440,80)
        p.field(f'mark-{i}',560 if p.portrait else 1450,y+120 if p.portrait else y+32,424 if p.portrait else 374,62,colour='attention' if p.raw[f'mark-{i}']=='LOOK CLOSER' else 'subject5')
        p.field(f'note-{i}',96,y+195 if p.portrait else y+82,888 if p.portrait else 1250,52,colour='quiet')

RENDER.update(cast=render_cast,collapse=render_collapse,mechanism=render_mechanism,bill=render_bill,ended=render_ended,clock=render_clock,toy=render_toy,press=render_press,flags=render_flags)

def render_promises(p):
    p.title();maximum=3 if p.portrait else 4;n=p.count('row-count',1,maximum)
    p.region('promise-area',[96,330 if p.portrait else 275,p.w-192,maximum*(430 if p.portrait else 174)],())
    for i in range(1,maximum+1):
        y=(330 if p.portrait else 275)+(i-1)*(430 if p.portrait else 174);active=i<=n
        if active:
            quote=p.require(f'promise-{i}');p.require(f'said-{i}');mark=p.require(f'mark-{i}')
            has_number=bool(re.search(r'\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion)\b',quote,re.I))
            has_date=bool(p.raw.get(f'target-period-{i}')) or bool(re.search(r'\b(next year|this year|next quarter|by year.end|FY\d|Q[1-4])\b',quote,re.I))
            if not has_number and not has_date:check(mark=='DROPPED','A promise with no number and no date can only be DROPPED')
            if mark=='DROPPED':check(p.raw[f'no-longer-mentioned-{i}']=='YES','DROPPED needs a record that they stopped mentioning the promise')
            else:p.require(f'result-{i}')
            if p.raw.get(f'result-{i}'):
                sheet=p.raw[f'result-sheet-{i}'];field=p.raw[f'result-field-{i}'];period=p.raw[f'result-period-{i}']
                check(field in p.item['workbookFields'].get(sheet,[]),'Result must name an actual workbook field_key on its sheet')
                check(re.fullmatch(r'Q-[0-7]' if sheet=='Quarters' else r'FY-[0-4]|LTM',period),'Result period does not belong to its workbook sheet')
            p.line([(96,y-10),(p.w-96,y-10)],'rule',2)
        boxes=[(f'promise-{i}',96,y+8,888 if p.portrait else 1030,145 if p.portrait else 120),
               (f'said-{i}',96,y+165 if p.portrait else y+126,888 if p.portrait else 1030,60 if p.portrait else 42),
               (f'result-{i}',96 if p.portrait else 1170,y+260 if p.portrait else y+38,460 if p.portrait else 300,100),
               (f'mark-{i}',590 if p.portrait else 1530,y+280 if p.portrait else y+54,394 if p.portrait else 294,70)]
        for name,x,yy,w,h in boxes:p.field(name,x,yy,w,h,value=p.values.get(name,'') if active else '',colour='attention' if name.startswith('mark') and p.raw.get(name)=='MISSED' else 'subject5' if name.startswith('mark') and p.raw.get(name)=='KEPT' else 'structure')

def twelve_months_before(stamp):
    d=datetime.fromtimestamp(stamp,timezone.utc);y=d.year-1
    return moment(d.replace(year=y,day=min(d.day,calendar.monthrange(y,d.month)[1])).isoformat())

def render_insiders(p):
    p.title();prices=price_series(p,'price-data');check(prices,'A trade chart needs the fetched price history')
    box=[232,390,706,590] if p.portrait else [224,280,1560,420]
    xy=plot(p,'price-area',box,[('subject',prices)]);lookup=dict(prices);trades=[]
    for i,row in enumerate(rows(p.raw['trade-data'])):
        if isinstance(row,dict):row=[row.get('date'),row.get('code'),row.get('value'),row.get('person'),row.get('planned','NO'),row.get('tax','NO')]
        check(len(row)==6,'Form 4 rows need date,code,value,person,planned,tax')
        stamp=moment(row[0]);code=str(row[1]).strip().upper()
        if code not in ('P','S') or not prices[0][0]<=stamp<=prices[-1][0]:continue
        check(stamp in lookup,'An open-market trade needs a fetched price observation on its actual day')
        amount=number(p.item,'trade-data row '+str(i+1),{'unit':'money'},str(row[2]),p.raw);check(amount>=0,'Trade value must be nonnegative')
        flags=[('YES' if v else 'NO') if type(v)is bool else str(v).strip().upper() for v in row[4:]];check(all(v in ('YES','NO') for v in flags),'Trade planned/tax flags must be YES or NO')
        person=str(row[3]).strip();check(person,'A Form 4 trade needs its reporting person')
        trades.append({'date':stamp,'code':code,'value':amount,'person':person,'planned':flags[0]=='YES','tax':flags[1]=='YES','point':xy(stamp,lookup[stamp])})
    p.region('trade-marks',box,('trade_marks',));p.add_nodes(long_series.trade_marks(dict(zip(('x','y','w','h'),box)),trades,p.ink))
    threshold=twelve_months_before(prices[-1][0]);recent=[t for t in trades if threshold<t['date']<=prices[-1][0]]
    for code,name,people in [('P','bought-12m','buyers'),('S','sold-12m','sellers')]:
        total=sum(t['value'] for t in recent if t['code']==code)
        # Computed feed totals retain dollars for small real trades, rather
        # than falsely printing zero million. Source parsing is still strict.
        p.values[name]=fmt(total/1e6,'money_m') if total>=1e6 else fmt(total,'money')
        p.values[people]=str(len({t['person'] for t in recent if t['code']==code}))
    for i,name in enumerate(('bought-12m','sold-12m')):
        x=96+i*(p.w-192)/2;y=1190 if p.portrait else 800
        p.field('bought-label' if i==0 else 'sold-label',x,y,(p.w-192)/2-28,54)
        p.field(name,x,y+66,(p.w-192)/2-28 if p.portrait else 590,160 if p.portrait else 140,colour='subject5' if i==0 else 'attention')
        people='buyers' if i==0 else 'sellers';px=x if p.portrait else x+650;py=y+246 if p.portrait else y+66
        p.field(people,px,py,150,85)
        p.field(people+'-label',x+170 if p.portrait else px,py+10 if p.portrait else py+90,(p.w-192)/2-200 if p.portrait else 200,60,value=people.upper(),role='label')
    selected=p.count('focus-trade',0,len(trades));focus=trades[selected-1]['point'] if selected else (box[0],box[1])
    p.region('trade-focus',[focus[0]-34,focus[1]-34,68,68],())
    if selected:p.line([(focus[0]+31*math.cos(k*math.pi/16),focus[1]+31*math.sin(k*math.pi/16)) for k in range(33)],'attention',4)
    p.field('callout',96,1660 if p.portrait else 1010,p.w-192,140 if p.portrait else 65)

def render_driver(p):
    p.title();stock=price_series(p,'stock-data');driver=price_series(p,'driver-data',p.raw['driver-unit'],False)
    common=sorted(set(dict(stock))&set(dict(driver)));check(len(common)>=2,'Index both series only on dates observed in both feeds')
    a=dict(stock);b=dict(driver);check(a[common[0]]>0 and b[common[0]]>0,'Both indexed series need a positive value on the shared start date')
    stock_line=[(d,a[d]/a[common[0]]*100) for d in common];driver_line=[(d,b[d]/b[common[0]]*100) for d in common]
    box=[232,470,706,680] if p.portrait else [224,320,1560,420]
    plot(p,'pair-area',box,[('subject',stock_line),('subject2',driver_line)],yunit='index',parts=['stock-line','driver-line'],gap=p.raw['show-gap']=='YES')
    if p.raw['show-gap']!='YES':p.region('pair-area-gap',box,('spread_fill',))
    p.field('stock-label',96,330 if p.portrait else 230,360 if p.portrait else 600,70,colour='subject')
    p.field('driver-label',500 if p.portrait else 900,330 if p.portrait else 230,484 if p.portrait else 924,70)
    p.values['stock-change']=fmt((a[common[-1]]/a[common[0]]-1)*100,'percent',1);p.values['driver-change']=fmt((b[common[-1]]/b[common[0]]-1)*100,'percent',1)
    p.values['start-label']=datetime.fromtimestamp(common[0],timezone.utc).date().isoformat();p.values['end-label']=datetime.fromtimestamp(common[-1],timezone.utc).date().isoformat()
    for i,name in enumerate(('stock-change','driver-change')):p.field(name,96+i*(p.w-192)/2,1370 if p.portrait else 850,(p.w-192)/2-30,140)
    p.field('start-label',96,1610 if p.portrait else 990,480,60);p.field('end-label',p.w-576,1610 if p.portrait else 990,480,60,align='right')
    p.field('index-unit',96,1220 if p.portrait else 780,p.w-192,60,value='INDEX / SAME START = 100 / ONE SCALE',role='unit')

def render_checked(p):
    p.title();source=p.require('found-source');stamp=re.search(r'\d{4}-\d{2}-\d{2}',source)
    check(stamp and len(re.sub(r'[^A-Za-z]','',source))>=3,'Name the checked page and its ISO date in found-source')
    date.fromisoformat(stamp[0]);p.require('claim');p.require('claim-source');p.require('found');p.require('verdict')
    p.region('comparison-area',[96,320,p.w-192,1280 if p.portrait else 520],())
    for i,(name,cite,figure) in enumerate((('claim','claim-source','claim-figure'),('found','found-source','found-figure'))):
        x=96 if p.portrait else 96+i*888;y=350+i*660 if p.portrait else 310;w=888 if p.portrait else 840
        p.card(x,y,w,580 if p.portrait else 520)
        p.field(name,x+26,y+28,w-52,260)
        p.field(cite,x+26,y+320,w-52,100 if p.portrait else 86,colour='quiet')
        p.field(figure,x+26,y+440,w-52,112)
    p.field('verdict',96,1710 if p.portrait else 940,p.w-192,90,colour='attention' if p.raw['verdict']=="DOESN'T" else 'structure')

def add_months(stamp,n):
    d=datetime.fromtimestamp(stamp,timezone.utc);y,m=divmod(d.year*12+d.month-1+n,12);m+=1
    return moment(d.replace(year=y,month=m,day=min(d.day,calendar.monthrange(y,m)[1])).isoformat())

def render_precedent(p):
    p.title();past=price_series(p,'then-data');now=price_series(p,'now-data');check(past and now,'Both actual price paths are required')
    then_event=moment(p.require('then-event'));now_event=moment(p.require('now-event'));a=dict(past);b=dict(now)
    check(then_event in a and now_event in b,'Day zero must have an observed close for each company')
    check(a[then_event]>0 and b[now_event]>0,'Day-zero closes must be positive for indexing')
    points=[[( (d-then_event)/(86400*365.25/12),v/a[then_event]*100) for d,v in past],[( (d-now_event)/(86400*365.25/12),v/b[now_event]*100) for d,v in now]]
    box=[232,470,706,680] if p.portrait else [224,320,1560,420]
    x0=min(v[0] for s in points for v in s);x1=max(v[0] for s in points for v in s)
    xy=plot(p,'paths-area',box,[('subject2',points[0]),('subject',points[1])],xdomain=(x0,x1),xunit='count',yunit='index',parts=['then-line','now-line'])
    check(x0<=0<=x1,'The price paths must include their event day')
    p.region('event-zero',box,('axis_mark',));p.series_nodes('axis_mark',core.native_series.axis_mark(dict(zip(('x','y','w','h'),box)),(0-x0)/(x1-x0),p.ink,tone='attention',weight=4)['nodes'])
    parent=next(r for r in p.regions if r['name']=='paths-area');parent['children'].append('event-zero')
    horizon=p.count('months-horizon',1,120);target=add_months(then_event,horizon)
    check(target<=past[-1][0],'The past data ends before the requested result; never extrapolate it')
    last=max((q for q in past if then_event<=q[0]<=target),default=None);check(last,'No past observation within the requested horizon')
    p.values['then-after']=fmt((last[1]/a[then_event]-1)*100,'percent',1);p.values['now-after']=fmt((now[-1][1]/b[now_event]-1)*100,'percent',1);p.values['months-after']=str(horizon)+' months on'
    p.field('then-name',96,330 if p.portrait else 230,400 if p.portrait else 780,70)
    p.field('now-name',530 if p.portrait else 1000,330 if p.portrait else 230,454 if p.portrait else 824,70,colour='subject')
    p.field('event-label',96,1220 if p.portrait else 780,p.w-192,75,colour='attention')
    p.field('then-after',96,1370 if p.portrait else 865,420 if p.portrait else 760,120)
    p.field('now-after',564 if p.portrait else 1060,1370 if p.portrait else 865,420 if p.portrait else 764,120,colour='subject')
    p.field('months-after',96,1530 if p.portrait else 985,p.w-192,70)
    p.field('month-unit',96,1650 if p.portrait else 1030,p.w-192,44,value='MONTHS FROM THE EVENT / INDEX AT DAY 0 = 100',role='unit')

RENDER.update(promises=render_promises,insiders=render_insiders,driver=render_driver,checked=render_checked,precedent=render_precedent)

def question_stress(p):
    q=p.raw['question'];selected=p.raw.get('stress-words','')
    if not selected:
        ordinary={'what','where','when','why','who','how','does','do','is','are','was','were','the','a','an','to','of','it','actually','can','should','would','could','will','which','this','that','these','those','about','on','for','with'}
        words=re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?",q)
        selected=next((w for w in words if w.lower()not in ordinary),words[-1] if words else '')
    start=q.casefold().find(selected.casefold());check(selected and start>=0,'Stress words must occur in the question')
    return {'start':start,'end':start+len(selected),'text':q[start:start+len(selected)]}

def render_question(p):
    q=p.require('question')
    check(q.endswith('?') and q.count('?')==1,'Write one question ending in ?, with no answer')
    check(not re.search(r'\d|[$€£%]|\b(hundred|thousand|million|billion|trillion|percent|dollars)\b',q,re.I),'The question card must not contain a figure')
    question_stress(p)
    p.field('kicker',96,370 if p.portrait else 180,p.w-192,70,align='center',colour='quiet')
    p.field('question',96 if p.portrait else 160,570 if p.portrait else 300,888 if p.portrait else 1600,780 if p.portrait else 480,align='center')

RENDER['question']=render_question

def motion_for(p):
    model=p.item['model'];steps=[]
    if model=='cast':
        steps=[group('title',cue='title')];n=p.count('player-count',1,6)
        for i in range(1,n+1,2):
            names=[f'{prefix}-{j}' for j in range(i,min(i+2,n+1)) for prefix in ('name','role','status')]
            steps.append(group(names[0],*names[1:],cue=names[0],effects=[effect('highlight',f'status-{j}',f'status-{j}') for j in range(i,min(i+2,n+1))]))
    elif model=='collapse':
        steps=[group('fall-line',move='line-draw' if p.raw.get('price-data') else None,cue='title')];n=p.count('event-count',0,6)
        for i in range(1,n+1,2):
            names=[f'{prefix}-{j}' for j in range(i,min(i+2,n+1)) for prefix in ('event','when','pin','pin-area')]
            steps.append(group(names[0],*names[1:],cue=names[0]))
        steps.append(group('drop',move='count-up',cue='drop'))
        if len(steps)<3:steps.insert(1,group('top','bottom',cue='top'))
    elif model=='mechanism':
        for i in range(1,p.variant['steps']+1):
            names=[f'detail-{i}',f'ordinal-{i}']+([f'arrow-{i}'] if i<p.variant['steps'] else [])
            steps.append(group(f'step-{i}',*names,cue=f'step-{i}'))
        steps.append(group('stop-mark','stop-label',move='pen-circle',cue='stop-label'))
    elif model=='bill':
        largest=max(range(1,p.count('party-count',1,6)+1),key=lambda i:p.num(f'amount-{i}'))
        steps=[group('bill-area',move='bars-grow',cue=f'party-{largest}'),group('fine-bar','fine-amount','fine-label',move='bars-grow',cue='fine-label'),group('ratio',move='count-up' if p.values['ratio']!='N/A' else None,cue='ratio')]
    elif model=='ended':
        n=p.count('row-count',1,5)
        for i in range(1,n+1):steps.append(group(f'name-{i}',f'role-{i}',f'outcome-{i}',f'ladder-row-{i}',cue=f'name-{i}'))
        if p.raw.get('what-changed'):steps.append(group('what-changed',cue='what-changed'))
    elif model=='clock':
        active=[i for i in range(1,5) if p.raw.get(f'total-{i}')]
        steps=[group('clock-start','clock-end','kicker','total-label','caption',cue='clock-start')]
        for i in active:
            steps.append(group('clock-area',f'at-{i}',f'total-{i}','live-total',move='clock-run',cue=f'total-{i}',cueAt='checkpoint-end',fromTimeSlot='clock-start' if i==1 else f'at-{i-1}',toTimeSlot=f'at-{i}',fromValueSlot=None if i==1 else f'total-{i-1}',toValueSlot=f'total-{i}',totalSlot='live-total',initialValue=0,continuousBetweenCheckpoints=True,restOnlyAtDocumentedCheckpoints=True))
        steps.append(group('live-total',move='highlight',cue=f'total-{active[-1]}'))
    elif model=='toy':
        steps=[group('title','tag',cue='title')];n=p.count('row-count',1,5)
        for i in range(1,n+1):steps.append(group(f'step-{i}',f'amount-{i}',f'total-{i}',*(['outcome'] if i==n else []),cue=f'step-{i}',effects=[effect('count-up',f'total-{i}',f'total-{i}')]+([effect('highlight',f'total-{i}',f'total-{i}')] if i==n else [])))
    elif model=='press':steps=[group('headline','source','date','body','caption'),group('mark-area',move='highlight',cue='body',cueRangeFrom='marked-sentence'),group('mark-area',move='zoom-to-slot',cue='body',cueRangeFrom='marked-sentence')]
    elif model=='flags':
        steps=[group('title',cue='title')]
        for a,b in ((1,3),(3,5),(5,6)):
            names=[f'{prefix}-{i}' for i in range(a,b) for prefix in ('check','figure','mark','note')]
            steps.append(group(names[0],*names[1:],cue=names[0]))
        flagged=[i for i in range(1,6) if p.raw[f'mark-{i}']=='LOOK CLOSER']
        if flagged:steps.append(group(f'mark-{flagged[0]}',move='highlight',cue=f'mark-{flagged[0]}',effects=[effect('highlight',f'mark-{i}',f'mark-{i}') for i in flagged[1:]]))
    elif model=='promises':
        steps=[group('title',cue='title')]
        for i in range(1,p.count('row-count',1,3 if p.portrait else 4)+1):
            effects=[effect('highlight',f'mark-{i}',f'mark-{i}')]
            if p.raw.get(f'result-{i}'):effects.insert(0,effect('count-up',f'result-{i}',f'result-{i}'))
            steps.append(group(f'promise-{i}',f'said-{i}',f'result-{i}',f'mark-{i}',action='clip-in',cue=f'promise-{i}',direction='left',effects=effects))
    elif model=='insiders':steps=[group('price-area',move='line-draw',cue='title'),group('trade-marks',cue='callout'),group('bought-12m','sold-12m','buyers','sellers',move='count-up',cue='bought-label',effects=[effect('count-up','sold-12m','sold-label')]),group('trade-focus','callout',move='pen-circle' if p.num('focus-trade') else None,cue='callout')]
    elif model=='driver':
        steps=[group('stock-line',move='line-draw',cue='title'),group('driver-line',move='line-draw',cue='driver-label'),group('stock-change','driver-change',move='count-up',cue='stock-change',effects=[effect('count-up','driver-change','driver-change')])]
        if p.raw['show-gap']=='YES':steps.append(group('pair-area-gap',move='highlight'))
    elif model=='checked':
        steps=[group('claim','claim-source',action='clip-in',cue='claim',direction='left')]
        if p.raw.get('claim-figure'):steps.append(group('claim-figure',move='count-up',cue='claim-figure'))
        steps.append(group('found','found-source',action='clip-in',cue='found',direction='left'))
        if p.raw.get('found-figure'):steps.append(group('found-figure',move='count-up',cue='found-figure'))
        steps.append(group('verdict',move='highlight',cue='verdict'))
    elif model=='precedent':steps=[group('then-line',move='line-draw',cue='then-name'),group('event-zero','event-label',cue='event-label'),group('now-line','now-after',move='line-draw',cue='now-name'),group('then-after','months-after',move='count-up',cue='then-after')]
    elif model=='question':steps=[group('question','kicker',cue='question'),group('question',move='highlight',cue='question',textRange=question_stress(p))]
    if len(steps)<3 and model!='question':
        last=next((s['name'] for s in reversed(p.slots) if s['example'] and s['role'] in ('caption','label','value','callout')),None)
        while len(steps)<3:steps.append(group(last,move='highlight',cue=last))
    mentioned={n for s in steps for n in (s['slot'],*s.get('includeSlots',[]))}
    context=[s['name'] for s in p.slots if s['name'] not in mentioned]+[r['name'] for r in p.regions if r['name'] not in mentioned and not r.get('composite')]
    if steps:steps[0]['includeSlots'].extend(context)
    return {'steps':steps}

def render(item,aspect,values,inks=None,variant=None):
    raw,visible,numbers=normalize(item,aspect,values,variant);p=Canvas(item,aspect,raw,visible,numbers,inks,variant)
    RENDER[item['model']](p)
    core.finite(p.nodes);return p

def writer_fields(entry):
    return {n:{**s,'maxChars':s.get('inputMaxChars',s['maxChars'])} for n,s in entry['slots'].items()
            if not s.get('computed') and (not s.get('region') or s.get('inputOnly'))}

def prepare(entry,values,inks):
    r=entry['longRecipe'];p=render(r['item'],r['aspect'],values,inks,r.get('variant'))
    visible={s['name']:s['example'] for s in p.slots};boxes={s['name']:s['box'] for s in p.slots}
    for name,value in visible.items():check(len(value)<=entry['slots'][name]['maxChars'],name+' exceeds its formatted text budget')
    boxes.update({r['name']:r['box'] for r in p.regions})
    return {'nodes':core.clean_nodes([n for n in p.nodes if n.get('_scope')=='body']),
            'values':visible,'boxes':boxes,'colours':{s['name']:s['colour'] for s in p.slots},
            'units':{s['name']:unit_for(s['spec'],p.raw) for s in p.slots},
            'motion':motion_for(p),'motionAnchors':anchors_for(p),'sources':resolved_sources(p)}

def resolved_sources(p):
    result={}
    for name,spec in p.specs.items():
        if not spec.get('source'):continue
        source=deepcopy(spec['source'])
        if spec.get('sourceFrom') and p.raw.get(spec['sourceFrom']):
            selected=p.raw[spec['sourceFrom']]
            if re.fullmatch(r'D\d+\.\d+(?:\s*,\s*D\d+\.\d+)*',selected):
                refs=[r.strip() for r in selected.split(',')]
                source={'kind':'document','what':spec['note'],'sentence':refs[0],'sentences':refs,'period':'the cited document periods'}
                if spec['source'].get('calculation') and unit_for(spec,p.raw)==spec['unit']:source['calculation']=spec['source']['calculation']
            elif selected.startswith('feed '):
                feed=selected[5:].strip();check(feed in ('edgar','price','fred','form4','web_shots'),'Unknown figure feed')
                source={'kind':'feed','feed':feed,'what':spec['note'],'period':'the stated observation window'}
            else:
                match=re.fullmatch(r'(History|Quarters|Snapshot)!([a-z][a-z0-9_]*),\s*(.+)',selected)
                check(match,'Figure source must name Sheet!field_key, period; a feed; or document sentences such as D2.14')
                sheet,field,period=match.groups();check(field in p.item['workbookFields'].get(sheet,[]),'Unknown workbook figure source')
                source={'kind':'workbook','sheet':sheet,'field':field,'period':period}
                if field=='accounts_receivable':source['pending']=True
        if p.item['model']=='collapse' and p.raw.get('price-data') and name in ('top','bottom','drop'):
            source={'kind':'feed','feed':'price','what':name+' from the observed collapse price series','period':'the requested dated interval'}
        for key,selector in (('field','fieldSlot'),('sheet','sheetSlot'),('period','periodSlot'),('location','locationSlot')):
            if source.get(selector):source[key]=p.raw.get(source[selector],source.get(key))
        if name in ('body','headline') and p.raw.get(name+'-ref'):source['sentence']=p.raw[name+'-ref']
        if source.get('pageDateSlot'):source['pageAndDate']=p.raw[source['pageDateSlot']]
        result[name]=source
    return result

def draw(region,numbers,inks):
    recipe=region['recipe'];p=render(recipe['item'],recipe['aspect'],numbers,inks,recipe.get('variant'))
    names={recipe['region']}
    for r in p.regions:
        if r['name']==recipe['region']:names.update(r.get('children',[]))
    nodes=[n for n in p.nodes if n.get('_region') in names]
    return [data._transform_node(n,recipe['nativeBox'],region) for n in nodes]

def labels(region,numbers,inks):
    recipe=region['recipe'];p=render(recipe['item'],recipe['aspect'],numbers,inks,recipe.get('variant'))
    sx,sy,sw,sh=recipe['nativeBox'];kx=region['w']/sw;ky=region['h']/sh;result=[]
    for s in p.slots:
        x,y,w,h=s['box'];result.append({'slot':s['name'],'text':s['example'],'box':[region['x']+(x-sx)*kx,region['y']+(y-sy)*ky,w*kx,h*ky]})
    return result

def group(slot,*others,action='appear',cue=None,move=None,effects=None,**params):
    step={'slot':slot,'includeSlots':list(others),**params}
    step['move' if move else 'action']=move or action
    if cue:step['cueSlot']=cue
    if effects:step['effects']=effects
    return step

def effect(move,slot,cue=None,**params):return {'move':move,'slot':slot,**({'cueSlot':cue} if cue else {}),**params}

def validate_motion(recipe,slots):
    check(2<=len(recipe['steps'])<=6,'A motion recipe needs two to six ideas')
    for step in recipe['steps']:
        check(step.get('move',step.get('action')) in MOVES,'Unknown motion move')
        for n in (step['slot'],*step.get('includeSlots',[])):check(n in slots,'Motion uses unpublished slot '+n)
        for cue in ([step['cueSlot']] if step.get('cueSlot') else []):
            check(cue in slots and not slots[cue].get('region') and (slots[cue]['role'] not in ('unit','legend','colHead','source','date') or slots[cue].get('spoken')),'A cue needs spoken words')
        for fx in step.get('effects',[]):
            check(fx['move'] in MOVES and fx['slot'] in slots,'Effect uses an unpublished move/slot')
            if fx.get('cueSlot'):check(fx['cueSlot'] in slots and not slots[fx['cueSlot']].get('region'),'Effect cue must be visible words')

def anchors_for(p):
    boxes={s['name']:s['box'] for s in p.slots};boxes.update({r['name']:r['box'] for r in p.regions});anchors=[]
    for step in motion_for(p)['steps']:
        for use in ([step] if step.get('move') else [])+step.get('effects',[]):
            anchors.append({'move':use['move'],'slot':use['slot'],'box':dict(zip(('x','y','w','h'),boxes[use['slot']]))})
    return anchors

def compile_plate(item,aspect,inks,scale,variant=None):
    from .build_all import fit
    fields=field_specs(item,aspect,variant);example={**item['example'],**item.get('exampleByAspect',{}).get(aspect,{})};fill={n:example.get(n,s.get('default','')) for n,s in fields.items() if not s.get('computed')}
    p=render(item,aspect,fill,variant=variant);slots={};roles={};examples=deepcopy(fill);audit=[]
    fitted={}
    for raw in p.slots:
        size,lines,_=fit(raw);role=raw['role'];fitted[role]=min(fitted.get(role,size),size)
    for raw in p.slots:
        name=raw['name'];spec=raw['spec'];role=raw['role'];size=fitted[role]
        _,lines,_=fit({**raw,'size':size});x,y,w,h=raw['box']
        cap=spec['maxChars'];colour=raw['colour']
        if core.contrast(inks[colour],inks['ground'])<4.5:colour='structure'
        roles[role]={'font':raw['font'],'weight':raw['weight'],'size':size,'colour':'structure','maxChars':min(cap,roles.get(role,{}).get('maxChars',cap)),'tracking':'0em','transform':'none'}
        slot={**deepcopy(spec),'x':x,'y':y,'w':w,'h':h,'role':role,'colour':colour,'align':raw['align'],'authoredLines':len(lines),'fit':'wrap','sourceUnit':spec['unit']}
        if spec['unit'] in ('money','money_m','shares_m','percent','multiple','count'):slot['inputMaxChars']=64
        slots[name]=slot;examples[name]=raw['example'];audit.append({'slot':name,'role':role,'font':raw['font'],'weight':raw['weight'],'size':size,'lines':lines})
    for name,spec in fields.items():
        if name in slots or spec.get('computed'):continue
        slots[name]={**deepcopy(spec),'x':0,'y':0,'w':0,'h':0,'role':'control','align':'left','maxChars':spec['maxChars'],'authoredLines':0,'fit':'none','region':True,'inputOnly':True,'renderer':'source_value','sourceUnit':spec['unit']}
    inputs=[n for n,s in slots.items() if not s.get('computed')]
    for region in p.regions:
        name=region['name'];x,y,w,h=region['box'];slots[name]={'x':x,'y':y,'w':w,'h':h,'role':'plot-area','align':'left','maxChars':0,'authoredLines':0,'fit':'none','region':True,'computed':True,
            'renderer':'design.longs.draw','labelRenderer':'design.longs.labels','uses':region['uses'],'inputSlots':inputs,'note':'Pure Python shapes and computed axes; no live fetch or writer geometry.',**({k:region[k] for k in ('children','composite') if k in region}),
            'recipe':{'item':deepcopy(item),'aspect':aspect,'variant':variant,'region':name,'nativeBox':region['box']}}
    key=item['key']+('-'+variant['id'] if variant else '')+'-'+aspect;file=key.split('/')[1]+'.png'
    motion=motion_for(p);validate_motion(motion,slots)
    entry={'key':key,'baseKey':item['key'],'dir':item['key'].split('/')[0],'aspect':aspect,'canvas':[p.w,p.h],'exportScale':scale,'delivered':[p.w*scale,p.h*scale],
        'ground':'paper','bakedText':False,'playback':'static','fps':0,'frameCount':1,'files':{'base':file,'baseIsFrame':True,'frames':[{'file':file,'tag':'','args':{}}]},
        'slots':slots,'slotCount':len(slots),'typeRoles':roles,'example':examples,'typeAudit':audit,'purpose':item['purpose'],'caution':item['caution'],'chapterTypes':item['chapterTypes'],'sectors':[],
        'motion':motion,'motionAnchors':anchors_for(p),'longRecipe':{'item':deepcopy(item),'aspect':aspect,'variant':variant}}
    if item.get('synthetic'):entry['factCheck']={'skipWhen':{'slot':'tag','values':['EXAMPLE','TOY NUMBERS']},'synthetic':True}
    if item.get('existingCounterpart'):entry['existingCounterpart']=item['existingCounterpart']
    if item['model']=='question':entry['typeRoles']['big'].update(valign='middle',maxLines=5 if aspect=='9x16' else 3)
    return entry,core.clean_nodes([n for n in p.nodes if n['_scope']=='frame'])
