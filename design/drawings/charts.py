"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
import math
import statistics
from collections import Counter
from datetime import date
from . import stock as base
from .. import core as studio
COLOURS = ['subject', 'subject2', 'subject3', 'subject4', 'subject5']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def numeric(values, *, positive=False):
    require(isinstance(values, list) and len(values) > 0, 'nonempty numeric list required')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in values), 'finite numeric data required')
    if positive:
        require(min(values) > 0, 'values must be positive')
    return values


def same(*arrays):
    require(len({len(a) for a in arrays}) == 1 and len(arrays[0]) > 0, 'aligned nonempty arrays required')


def quantile(values, q):
    """Linear interpolation at (n-1)*q, also called the type-7 quantile."""
    values = sorted(numeric(values))
    require(0 <= q <= 1, 'quantile outside 0–1')
    pos = (len(values)-1)*q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi]-values[lo])*(pos-lo)


def correlation(a, b):
    same(a, b)
    numeric(a); numeric(b)
    require(len(a) >= 3, 'correlation needs at least three paired observations')
    da = [v-statistics.mean(a) for v in a]
    db = [v-statistics.mean(b) for v in b]
    denom = math.sqrt(sum(v*v for v in da)*sum(v*v for v in db))
    require(denom > 0, 'constant series has undefined correlation')
    return sum(x*y for x, y in zip(da, db))/denom


def iso_dates(labels):
    result = [date.fromisoformat(d).toordinal() for d in labels]
    require(all(a < b for a, b in zip(result, result[1:])), 'dates must be strictly increasing')
    return result


def cumsum(values, start=0):
    output = []
    for value in values:
        start += value
        output.append(start)
    return output


def n(value, places=1, signed=False):
    value = 0 if abs(value) < 1e-9 else value
    sign = '+' if signed and value > 0 else ''
    return sign + base.number(value, places)


def fmt(value, unit='', places=1, signed=False):
    v = n(value, places, signed)
    if unit == '$m':
        return ('-$'+v[1:] if v.startswith('-') else '$'+v)+'m'
    if unit == '$':
        return '-$'+v[1:] if v.startswith('-') else '$'+v
    return v+unit


def text(p, key, value, x, y, w, h=40, size=None, *, bold=False, mono=False,
         colour='structure', align='left', editable=True, background='ground'):
    bg=p.colour(background)
    if studio.contrast(p.colour(colour),bg)<4.5:
        choices=[p.colour('structure'),p.colour('ground'),studio.INKS['paper']['structure']]
        colour=max(choices,key=lambda candidate:studio.contrast(candidate,bg))
        if studio.contrast(colour,bg)<4.5:
            p.rect(x,y,w,h,'ground')
            background='ground';colour='structure'
    base.text(p, key, value, x, y, w, h, size or (34 if p.portrait else 28),
              mono=mono, bold=bold, colour=colour, align=align,
              editable=editable, background=background)


def label(p, key, value, x, y, w, h=40, **kw):
    text(p, key, value, x, y, w, h, mono=True, colour='quiet', editable=False, **kw)


def unit(p, value):
    label(p, 'chart-units', value, 96, 510 if p.portrait else 414, p.w-192, 42)


def legend(p, items, *, y=None):
    y = y if y is not None else (574 if p.portrait else 462)
    width = (p.w-192)/len(items)
    for i, item in enumerate(items):
        name, colour, *rest = item
        x = 96+i*width
        if rest and rest[0] == 'hollow':
            p.dot(x+9, y+15, colour, r=8, hollow=True)
        else:
            p.rect(x, y+6, 18, 18, colour,
                   'structure' if p.ground == 'paper' and colour != 'structure' else None, sw=2)
        label(p, f'legend-{i}', name, x+31, y, width-43, 40)


def summary(p, items):
    """Two measured callouts beneath the chart, outside the plot and tick labels."""
    y = 1160 if p.portrait else 832
    width = (p.w-192)/len(items)
    for i, (name, value) in enumerate(items):
        x = 96+i*width
        label(p, f'summary-label-{i}', name, x, y, width-20 if p.portrait else width-360, 38)
        text(p, f'summary-value-{i}', value, x, y+44 if p.portrait else y+2,
             width-20 if p.portrait else width-350, 58 if p.portrait else 42,
             52 if p.portrait else 43, mono=True, bold=True, colour='subject',
             align='left' if p.portrait else 'right') if p.portrait else text(
                 p, f'summary-value-{i}', value, x+width-338, y-1, 318, 43,
                 42, mono=True, bold=True, colour='subject', align='right')


def caption(p, value, key='chart-caption', y=None):
    text(p, key, value, 96, y if y is not None else (1160 if p.portrait else 833), p.w-192,
         90 if p.portrait else 44, 38 if p.portrait else 32, bold=True)


class Plot:
    def __init__(self, p, name, xdomain, ydomain, *, box=None):
        self.p, self.name = p, name
        self.x0, self.x1 = xdomain
        self.y0, self.y1 = ydomain
        require(self.x1 > self.x0 and self.y1 > self.y0, 'plot scales must be nonempty')
        self.box = list(box or ((232, 668, 706, 378) if p.portrait else (252, 523, 1476, 237)))
        self.left, self.top, self.width, self.height = self.box
        p.regions.append({'name': name, 'box': self.box, 'xDomain': list(xdomain), 'yDomain': list(ydomain)})

    def xy(self, x, y):
        require(math.isfinite(x) and math.isfinite(y), 'non-finite chart coordinate')
        eps = 1e-7
        require(self.x0-eps <= x <= self.x1+eps and self.y0-eps <= y <= self.y1+eps,
                f'{self.p.key}: point {(x, y)} outside declared scale {(self.x0,self.x1,self.y0,self.y1)}')
        return (self.left+(x-self.x0)/(self.x1-self.x0)*self.width,
                self.top+self.height-(y-self.y0)/(self.y1-self.y0)*self.height)

    def line(self, points, colour='subject', width=6, *, step=False, dash=False):
        if not self.p.filled:
            return
        coords = [self.xy(x, y) for x, y in points]
        if step:
            stepped = [coords[0]]
            for a, b in zip(coords, coords[1:]):
                stepped.extend([(b[0], a[1]), b])
            coords = stepped
        # Reuse the bot's existing pure line_path; the plate declares its x
        # anchors explicitly. Dots are authored separately by Plot.dot.
        box=dict(zip(('x','y','w','h'),self.box))
        columns=[{'anchorX':px} for px,_ in coords]
        values=[self.y0+(self.top+self.height-py)/self.height*(self.y1-self.y0) for _,py in coords]
        result=studio.native_series.line_path(box,values,self.p.ink,columns=columns,min=self.y0,max=self.y1,zero=False,tone=colour,weight=width)
        self.p.series_nodes('line_path',result['nodes'],dash=dash,paths_only=True)
        self.p.chart_marks.append({'plot': self.name, 'kind': 'step' if step else 'line',
                                   'data': points, 'pixels': coords})

    def dot(self, x, y, colour='subject', r=8, hollow=False):
        if not self.p.filled:
            return
        px, py = self.xy(x, y)
        self.p.dot(px, py, colour, r, hollow)
        self.p.chart_marks.append({'plot': self.name, 'kind': 'dot', 'data': [x,y], 'pixels': [[px,py]]})

    def area(self, upper, lower, colour='subject', opacity=.35):
        if self.p.filled:
            points = [self.xy(x, y) for x,y in upper] + [self.xy(x,y) for x,y in reversed(lower)]
            if len(upper)==len(lower) and len(upper)>=2 and all(a[0]==b[0] for a,b in zip(upper,lower)):
                box=dict(zip(('x','y','w','h'),self.box));columns=[{'anchorX':self.xy(x,y)[0]} for x,y in upper]
                result=studio.native_series.spread_fill(box,[v for _,v in upper],[v for _,v in lower],self.p.ink,columns=columns,min=self.y0,max=self.y1)
                self.p.series_nodes('spread_fill',result['nodes'],colour=colour)
            else:self.p.polygon(points, colour, opacity)
            self.p.chart_marks.append({'plot': self.name, 'kind': 'area', 'upper': upper, 'lower': lower, 'pixels': points})

    def bar(self, x, value, *, base_value=0, width=.65, colour='subject'):
        if not self.p.filled:
            return
        left, top = self.xy(x-width/2, max(value,base_value))
        right, bottom = self.xy(x+width/2, min(value,base_value))
        if base_value==0:
            col={'x':left,'y':self.top,'w':right-left,'h':self.height,'baselineY':self.xy(x,0)[1]}
            result=studio.native_series.column_bars([col],[value],self.p.ink,min=self.y0,max=self.y1,tone=colour)
            self.p.series_nodes('column_bars',result['nodes'])
        else:self.p.rect(left,top,right-left,max(0,bottom-top),colour,'structure',sw=2)
        self.p.chart_marks.append({'plot': self.name, 'kind': 'bar', 'data': [x,value,base_value],
                                   'pixels': [[left,top],[right,bottom]], 'zeroIncluded': self.y0 <= 0 <= self.y1})

    def axes(self, *, xticks=(), yticks=(), xformat=None, yformat=None, grid=True):
        p=self.p; x,y,w,h=self.box
        p.line([(x,y+h),(x+w,y+h)], 'axis', 3)
        for i, tick in enumerate(dict.fromkeys(yticks)):
            _, py = self.xy(self.x0, tick)
            if grid:
                p.line([(x,py),(x+w,py)], 'rule', 2)
            label(p, f'{self.name}-y-{i}', yformat(tick) if yformat else n(tick),
                  96 if p.portrait else max(96,x-148), py-15, x-(96 if p.portrait else max(96,x-148))-15,
                  34, align='right')
        coordinates=[self.xy(tick[0] if isinstance(tick,tuple) else tick,self.y0)[0] for tick in xticks]
        min_gap=min((b-a for a,b in zip(coordinates,coordinates[1:])),default=w)
        maxw = min(min_gap*.78, 208 if p.portrait else 270)
        for i, tick in enumerate(xticks):
            value, rendered = tick if isinstance(tick, tuple) else (tick, xformat(tick) if xformat else n(tick))
            px, _ = self.xy(value,self.y0)
            tx = max(96, min(px-maxw/2,p.w-96-maxw))
            label(p, f'{self.name}-x-{i}', rendered, tx, y+h+20, maxw, 55 if p.portrait else 40, align='center')

    def reference(self, *, y=None, x=None, colour='axis', dash=True):
        if y is not None:
            a=self.xy(self.x0,y); b=self.xy(self.x1,y)
        else:
            a=self.xy(x,self.y0); b=self.xy(x,self.y1)
        self.p.line([a,b], colour, 3, dash=dash)


def padded(values, *, zero=False, fraction=.12):
    lo,hi = min(values),max(values)
    if zero:
        lo=min(0,lo); hi=max(0,hi)
    span=max(hi-lo,abs(hi)*.1,1)
    return (lo-span*fraction if lo < 0 or not zero else 0,
            hi+span*fraction if hi > 0 or not zero else 0)


def date_xticks(labels, maximum=4):
    days=iso_dates(labels)
    indices=sorted({round(i*(len(days)-1)/(min(maximum,len(days))-1)) for i in range(min(maximum,len(days)))})
    return days, [(days[i], labels[i][2:7]) for i in indices]


def render_drawdown(p,c):
    d=c['data']; levels=numeric(d['levels'],positive=True); same(d['dates'],levels)
    dates,ticks=date_xticks(d['dates'])
    peaks=[]; peak=levels[0]
    for v in levels:
        peak=max(peak,v); peaks.append(peak)
    dd=[(v/peak-1)*100 for v,peak in zip(levels,peaks)]
    low=min(-10,math.floor(min(dd)/10)*10)
    unit(p, 'DRAWDOWN FROM PRIOR PEAK / %')
    a=Plot(p,'underwater',(dates[0],dates[-1]),(low,0))
    points=list(zip(dates,dd))
    a.axes(xticks=ticks,yticks=[low,low/2,0],yformat=lambda v:fmt(v,'%'))
    a.area([(x,0) for x in dates],points,'down',.48)
    a.line(points,'down')
    worst=min(range(len(dd)),key=dd.__getitem__); a.dot(dates[worst],dd[worst],'structure')
    summary(p,[('DEEPEST DRAWDOWN',fmt(min(dd),'%')),('LATEST VS PEAK',fmt(dd[-1],'%'))])
    return {'drawdown':dd,'runningPeak':peaks,'maxDrawdown':min(dd)}


def render_recovery(p,c):
    d=c['data']; losses=numeric(d['losses']); actual=d['actual_loss']
    require(min(losses)>=0 and max(losses)<100 and min(losses)<=actual<=max(losses),'loss must be 0–100% exclusive')
    xs=[i for i in range(int(min(losses)),int(max(losses))+1)]
    gains=[(1/(1-v/100)-1)*100 for v in xs]
    result=(1/(1-actual/100)-1)*100
    unit(p,'LOSS / % / GAIN NEEDED TO RECOVER / %')
    a=Plot(p,'rebound',(min(losses),max(losses)),(0,math.ceil(max(gains)/50)*50))
    a.axes(xticks=losses,yticks=[0,a.y1/2,a.y1],xformat=lambda v:fmt(v,'%'),yformat=lambda v:fmt(v,'%'))
    a.line(list(zip(xs,gains)));a.dot(actual,result,'subject2',r=11)
    summary(p,[('EXAMPLE LOSS',fmt(-actual,'%')),('REQUIRED GAIN',fmt(result,'%'))])
    return {'loss':actual,'requiredGain':result}


def horizontal_rows(p,c,rows,domain,*,unit_label,formatter,mode='dumbbell',labels=('PRIOR','CURRENT'),tick_formatter=None):
    """Shared numeric horizontal scale with a measured label and delta per row."""
    unit(p,unit_label)
    legend(p,[(labels[0],'subject','hollow'),(labels[1],'subject2')])
    left=350 if p.portrait else 600; right=910 if p.portrait else 1560
    top=690 if p.portrait else 533; spacing=110 if p.portrait else 65
    x0,x1=domain; require(x0<x1,'empty horizontal scale')
    h=(len(rows)-1)*spacing+24
    a=Plot(p,'row-scale',(x0,x1),(-.5,len(rows)-.5),box=(left,top,right-left,h))
    for j,(name,before,after) in enumerate(rows):
        y=top+j*spacing
        label(p,f'row-name-{j}',name,96,y-13,left-120,44 if p.portrait else 45)
        if p.filled:
            bx=left+(before-x0)/(x1-x0)*(right-left); ax=left+(after-x0)/(x1-x0)*(right-left)
            require(left<=bx<=right and left<=ax<=right,'row marker off scale')
            p.line([(bx,y+10),(ax,y+10)],'axis',6)
            if mode=='bullet':
                p.rect(left,y-2,max(0,bx-left),24,'subject')
                p.line([(ax,y-13),(ax,y+33)],'subject2',6)
            else:
                p.dot(bx,y+10,'subject',10,hollow=True);p.dot(ax,y+10,'subject2',10)
            p.chart_marks.append({'plot':'row-scale','kind':mode,'data':[before,after],
                                  'pixels':[[bx,y+10],[ax,y+10]]})
        text(p,f'row-delta-{j}',formatter(after-before),96 if p.portrait else 1600,
             y+49 if p.portrait else y-10,left-120 if p.portrait else 224,44,
             34 if p.portrait else 35,mono=True,bold=True,align='left' if p.portrait else 'right')
    yaxis=top+(len(rows)-1)*spacing+100 if p.portrait else 789
    for i,value in enumerate([x0,(x0+x1)/2,x1]):
        x=left+(right-left)*i/2
        label(p,f'row-tick-{i}',(tick_formatter or formatter)(value),x-70,yaxis,140,40,align='center')
    return a


def render_dumbbell(p,c):
    d=c['data']; same(d['labels'],d['before'],d['after'])
    numeric(d['before']);numeric(d['after'])
    rows=list(zip(d['labels'],d['before'],d['after']))
    horizontal_rows(p,c,rows,d['domain'],unit_label=d['units']+' / ROW LABEL = CHANGE',
                    formatter=lambda v:fmt(v,d.get('delta_unit',d['unit']),signed=True),labels=tuple(d['periods']),
                    tick_formatter=lambda v:fmt(v,d['unit']))
    caption(p,d['note'])
    return {'changes':[a-b for b,a in zip(d['before'],d['after'])]}


def render_horizons(p,c):
    d=c['data']; levels=numeric(d['levels'],positive=True)
    dates=iso_dates(d['dates']);same(dates,levels)
    values=[]
    for lookback in d['lookbacks']:
        idx=d['dates'].index(lookback['date'])
        values.append((levels[-1]/levels[idx]-1)*100)
    unit(p,'TRAILING PRICE RETURN / % / COMMON END DATE')
    top=665 if p.portrait else 524; spacing=105 if p.portrait else 70
    lo,hi=padded(values,zero=True)
    left=350 if p.portrait else 590;right=875 if p.portrait else 1550
    a=Plot(p,'horizon-returns',(lo,hi),(-.5,len(values)-.5),box=(left,top,right-left,spacing*(len(values)-1)+30))
    zero=left+(0-lo)/(hi-lo)*(right-left)
    p.line([(zero,top-24),(zero,top+spacing*(len(values)-1)+30)],'axis',3)
    for i,(lookback,v) in enumerate(zip(d['lookbacks'],values)):
        y=top+i*spacing
        label(p,f'horizon-{i}',lookback['label'],96,y-10,215,40)
        if p.filled:
            x=left+(v-lo)/(hi-lo)*(right-left)
            p.line([(zero,y+6),(x,y+6)],'down' if v<0 else 'subject',18)
            p.chart_marks.append({'plot':'horizon-returns','kind':'horizontal-bar','data':[0,v],
                                  'pixels':[[zero,y+6],[x,y+6]]})
        text(p,f'horizon-value-{i}',fmt(v,'%',signed=True),96 if p.portrait else 1590,
             y+44 if p.portrait else y-10,215 if p.portrait else 234,42,35,mono=True,bold=True,
             align='left' if p.portrait else 'right')
    for i,value in enumerate([lo,0,hi]):
        x=left+(value-lo)/(hi-lo)*(right-left)
        label(p,f'horizon-axis-{i}',fmt(value,'%'),x-70,1110 if p.portrait else 799,140,40,align='center')
    caption(p,'Same stock. Same end date. Different starting points.',y=1201 if p.portrait else 850)
    return {'returns':values,'endDate':d['dates'][-1]}


def render_gap_area(p,c):
    d=c['data'];same(d['dates'],d['price'],d['total_return'])
    numeric(d['price'],positive=True);numeric(d['total_return'],positive=True)
    require(d['price'][0]==d['total_return'][0]==100,'both return indices must start at 100')
    dates,ticks=date_xticks(d['dates'])
    lo,hi=padded(d['price']+d['total_return'])
    unit(p,'REBASED INDEX / START = 100')
    legend(p,[('PRICE ONLY','subject'),('REINVESTED','subject2')])
    a=Plot(p,'return-wedge',(dates[0],dates[-1]),(lo,hi))
    a.axes(xticks=ticks,yticks=[math.ceil(lo),100,math.floor(hi)],yformat=lambda v:n(v,0))
    upper=list(zip(dates,d['total_return']));lower=list(zip(dates,d['price']))
    a.area(upper,lower,'subject2',.35);a.line(lower);a.line(upper,'subject2')
    summary(p,[('PRICE RETURN',fmt(d['price'][-1]-100,'%',signed=True)),
               ('TOTAL RETURN',fmt(d['total_return'][-1]-100,'%',signed=True))])
    return {'priceReturn':d['price'][-1]-100,'totalReturn':d['total_return'][-1]-100}


def render_spells(p,c):
    d=c['data']; cutoff=date.fromisoformat(d['as_of']).toordinal()
    rows=[]
    for item in d['spells']:
        start=date.fromisoformat(item['peak']).toordinal(); trough=date.fromisoformat(item['trough']).toordinal()
        end=date.fromisoformat(item.get('recovery') or d['as_of']).toordinal()
        require(start<=trough<=end<=cutoff,'invalid drawdown spell ordering')
        rows.append((item,start,trough,end))
    unit(p,'CALENDAR DAYS / PEAK → TROUGH → RECOVERY')
    legend(p,[('FALLING','down'),('RECOVERING','subject')])
    xmin=min(r[1] for r in rows); xmax=cutoff
    left,right=(325,940) if p.portrait else (540,1640)
    top=708 if p.portrait else 542;spacing=147 if p.portrait else 94
    def x(value):return left+(value-xmin)/(xmax-xmin)*(right-left)
    for i,(item,start,trough,end) in enumerate(rows):
        y=top+i*spacing
        label(p,f'spell-name-{i}',item['name'],96,y-8,left-120,40)
        if p.filled:
            p.rect(x(start),y,x(trough)-x(start),28,'down')
            p.rect(x(trough),y,x(end)-x(trough),28,'subject')
            if not item.get('recovery'):
                p.line([(x(end)-24,y-8),(x(end),y+14),(x(end)-24,y+36)],'structure',4)
        value=f'{end-start}d'+(' OPEN' if not item.get('recovery') else '')
        text(p,f'spell-duration-{i}',value,96 if p.portrait else 1660,y+49 if p.portrait else y-3,
             300 if p.portrait else 164,40,34 if p.portrait else 28,mono=True,bold=True)
    for i,v in enumerate([xmin,(xmin+xmax)/2,xmax]):
        label(p,f'spell-date-{i}',date.fromordinal(round(v)).isoformat()[2:7],min(p.w-226,x(v)-65),
              1194 if p.portrait else 841,130,40,align='center')
    return {'durationsDays':[r[3]-r[1] for r in rows], 'open':[not bool(r[0].get('recovery')) for r in rows]}


def render_ecdf(p,c):
    d=c['data'];values=sorted(numeric(d['returns']));threshold=d['threshold']
    lo,hi=d['domain'];require(lo<=min(values) and max(values)<=hi,'CDF sample outside scale')
    counts=Counter(values);points=[(lo,0)];total=0
    for value,count in sorted(counts.items()):
        total+=count;points.append((value,total/len(values)*100))
    points.append((hi,100))
    unit(p,'DAILY RETURN, % / OBSERVATIONS AT OR BELOW')
    a=Plot(p,'ecdf',(lo,hi),(0,100))
    a.axes(xticks=[lo,0,hi],yticks=[0,50,100],xformat=lambda v:fmt(v,'%'),yformat=lambda v:fmt(v,'%'))
    a.reference(x=threshold);a.line(points,step=True)
    below=sum(v<=threshold for v in values)
    summary(p,[('AT / BELOW '+fmt(threshold,'%'),fmt(below/len(values)*100,'%')),
               ('OBSERVATIONS',str(len(values)))])
    return {'sampleSize':len(values),'thresholdCount':below,'cdf':points}


def render_histogram(p,c):
    d=c['data'];values=numeric(d['returns']);edges=numeric(d['edges'])
    require(all(b>a for a,b in zip(edges,edges[1:])),'histogram edges must increase')
    widths=[b-a for a,b in zip(edges,edges[1:])]
    require(max(widths)-min(widths)<1e-8,'count histogram requires equal-width bins')
    require(edges[0]<=min(values) and max(values)<=edges[-1],'all samples must be inside bins')
    counts=[0]*(len(edges)-1)
    for value in values:
        idx=next((i for i,(a,b) in enumerate(zip(edges,edges[1:])) if a<=value<b),len(counts)-1)
        counts[idx]+=1
    unit(p,'DAILY RETURN, % / COUNT PER 2pp BIN')
    legend(p,[('CENTRAL BINS','subject'),('OUTER BINS','subject2')])
    high=max(4,math.ceil(max(counts)/2)*2)
    a=Plot(p,'return-bins',(edges[0],edges[-1]),(0,high))
    a.axes(xticks=[edges[0],0,edges[-1]],yticks=[0,high/2,high],
           xformat=lambda v:fmt(v,'%'),yformat=lambda v:n(v,0))
    for i,count in enumerate(counts):
        center=(edges[i]+edges[i+1])/2
        a.bar(center,count,width=widths[i]*.9,colour='subject2' if abs(center)>=4 else 'subject')
    tails=sum(abs(v)>=4 for v in values)
    summary(p,[('TAIL DAYS',str(tails)+' / '+str(len(values))),('TAIL SHARE',fmt(tails/len(values)*100,'%'))])
    return {'edges':edges,'counts':counts,'tailCount':tails,'sampleSize':len(values)}


def render_boxplot(p,c):
    d=c['data'];same(d['labels'],d['samples'])
    require(len(d['labels'])==3,'boxplot uses three comparable groups')
    require(len({len(values) for values in d['samples']})==1,'boxplot caption requires equal sample counts')
    unit(p,'OPERATING MARGIN / % / EQUAL SAMPLE COUNTS')
    legend(p,[('BOX = Q1–Q3','subject'),('TICK = MEDIAN','subject2')])
    lo,hi=d['domain']; left,right=(360,915) if p.portrait else (620,1670)
    top=714 if p.portrait else 552;spacing=144 if p.portrait else 98
    summaries=[]
    for i,(name,values) in enumerate(zip(d['labels'],d['samples'])):
        values=numeric(values);require(lo<=min(values)<=max(values)<=hi,'box sample outside scale')
        q=[quantile(values,v) for v in [0,.25,.5,.75,1]];summaries.append(q)
        y=top+i*spacing
        label(p,f'box-name-{i}',name,96,y-12,left-(120 if p.portrait else 200),40)
        text(p,f'box-n-{i}','n='+str(len(values)),96,y+38,left-(120 if p.portrait else 200),40,mono=True)
        px=lambda v:left+(v-lo)/(hi-lo)*(right-left)
        if p.filled:
            p.line([(px(q[0]),y+10),(px(q[4]),y+10)],'axis',4)
            for value in (q[0],q[4]):p.line([(px(value),y-13),(px(value),y+33)],'axis',4)
            p.rect(px(q[1]),y-17,px(q[3])-px(q[1]),54,'subject','structure',sw=2)
            p.line([(px(q[2]),y-23),(px(q[2]),y+43)],'subject2',6)
    for i,v in enumerate([lo,(lo+hi)/2,hi]):
        label(p,f'box-axis-{i}',fmt(v,'%'),left+(right-left)*i/2-65,
              1140 if p.portrait else 795,130,40,align='center')
    caption(p,'Whiskers show the observed minimum and maximum.',y=1202 if p.portrait else 850)
    return {'fiveNumberSummaries':summaries,'method':'type-7; whiskers=min,max'}


def tint(p,value,limit=1):
    strength=min(1,abs(value)/limit)
    return p.colour('band' if strength<.2 else 'subject3' if value>=0 and strength<.65 else 'subject' if value>=0 else 'down')


def cell_text(p,key,value,x,y,w,h,background,size=None,editable=True):
    foreground=max((p.colour('structure'),p.colour('ground')),
                   key=lambda candidate:studio.contrast(candidate,background))
    text(p,key,value,x+8,y+(h-40)/2,w-16,40,size or (38 if p.portrait else 40),
         mono=True,bold=True,background=background,colour=foreground,align='center',editable=editable)


def render_correlation(p,c):
    d=c['data'];same(d['labels'],d['returns']);require(len(d['labels'])==4,'four assets required')
    matrix=[[correlation(a,b) for b in d['returns']] for a in d['returns']]
    unit(p,'PEARSON r / '+str(len(d['returns'][0]))+' MATCHED MONTHS')
    left,top,w,h=(280,704,672,432) if p.portrait else (530,520,1120,300)
    cw,ch=w/4,h/4
    for i,name in enumerate(d['labels']):
        text(p,f'corr-column-{i}',name,left+i*cw,top-56,cw,40,bold=True,align='center',editable=False)
        text(p,f'corr-row-{i}',name,96,top+i*ch+(ch-40)/2,left-115,40,bold=True,editable=False)
        for j,value in enumerate(matrix[i]):
            colour=tint(p,value) if p.filled else p.colour('band')
            p.rect(left+j*cw,top+i*ch,cw-5,ch-5,colour)
            cell_text(p,f'corr-{i}-{j}',n(value,2),left+j*cw,top+i*ch,cw-5,ch-5,colour)
    caption(p,'Co-movement in this sample; the relationship can change.')
    return {'correlations':matrix,'sampleSize':len(d['returns'][0])}


def render_rolling_risk(p,c):
    d=c['data'];returns=numeric(d['returns']);window=d['window']
    require(type(window) is int and 2<=window<len(returns),'invalid rolling window')
    risk=[statistics.stdev(returns[i-window+1:i+1])*math.sqrt(d['annual_sessions'])
          for i in range(window-1,len(returns))]
    unit(p,'DAILY RETURNS / ROLLING ANNUALISED VOL, %')
    topbox=(232,650,706,160) if p.portrait else (252,505,1476,110)
    bottombox=(232,908,706,170) if p.portrait else (252,704,1476,72)
    bound=max(1,math.ceil(max(abs(v) for v in returns)))
    a=Plot(p,'daily',(0,len(returns)-1),(-bound,bound),box=topbox)
    a.axes(yticks=[-bound,0,bound],yformat=lambda v:fmt(v,'%'))
    a.reference(y=0);a.line(list(enumerate(returns)),'axis',3)
    volmax=math.ceil(max(risk)/10)*10
    b=Plot(p,'rolling-vol',(0,len(returns)-1),(0,volmax),box=bottombox)
    b.axes(xticks=[(0,'DAY 1'),(len(returns)-1,'DAY '+str(len(returns)))],yticks=[0,volmax],yformat=lambda v:fmt(v,'%'))
    b.line(list(zip(range(window-1,len(returns)),risk)))
    label(p,'daily-label','DAILY',232 if p.portrait else 252,566 if p.portrait else 464,500,40)
    label(p,'risk-label',str(window)+'-DAY VOL',232 if p.portrait else 252,843 if p.portrait else 650,500,40)
    caption(p,'Same return series. A different view of the recent risk.',y=1197 if p.portrait else 846)
    return {'rollingVolatility':risk,'sampleWindow':window,'annualisation':d['annual_sessions']}


def render_bump(p,c):
    d=c['data'];rows=d['ranks'];same(d['labels'],rows)
    nfirms=len(rows);periods=len(d['periods'])
    require(nfirms==4 and periods==4,'rank chart uses four firms and four periods')
    require(all(len(r)==periods for r in rows),'rank rows must align')
    for i in range(periods):
        require(sorted(r[i] for r in rows)==list(range(1,nfirms+1)),'each period must be a complete ranking without ties')
    unit(p,'REVENUE RANK / 1 = LARGEST / NO TIES')
    legend(p,list(zip(d['labels'],COLOURS)))
    a=Plot(p,'ranks',(0,periods-1),(.5,nfirms+.5))
    a.axes(xticks=list(enumerate(d['periods'])),yticks=[1,2,3,4],yformat=lambda v:str(nfirms+1-int(v)))
    for i,row in enumerate(rows):
        points=[(j,nfirms+1-rank) for j,rank in enumerate(row)]
        a.line(points,COLOURS[i],5)
        for x,y in points:a.dot(x,y,COLOURS[i],r=9)
    caption(p,'Rank shows the order; it does not show the size of the gap.')
    return {'rankChanges':[r[0]-r[-1] for r in rows]}


def render_trajectory(p,c):
    d=c['data'];unit(p,'X: REVENUE GROWTH / Y: OP. MARGIN / %')
    legend(p,[(row['name'],COLOURS[i]) for i,row in enumerate(d['paths'])])
    a=Plot(p,'journeys',tuple(d['x_domain']),tuple(d['y_domain']))
    a.axes(xticks=[a.x0,0,a.x1],yticks=[a.y0,0,a.y1],xformat=lambda v:fmt(v,'%'),yformat=lambda v:fmt(v,'%'))
    a.reference(x=0);a.reference(y=0)
    changes=[]
    for i,row in enumerate(d['paths']):
        same(row['x'],row['y']);numeric(row['x']);numeric(row['y']);require(len(row['x'])>=2,'trajectory needs two dates')
        points=list(zip(row['x'],row['y']));a.line(points,COLOURS[i],5)
        a.dot(*points[0],COLOURS[i],r=9,hollow=True);a.dot(*points[-1],COLOURS[i],r=11)
        if p.filled:p.line([a.xy(*points[-2]),a.xy(*points[-1])],COLOURS[i],5,arrow=True)
        changes.append([row['x'][-1]-row['x'][0],row['y'][-1]-row['y'][0]])
    caption(p,'Open dot = earlier. Filled dot and arrow = later.')
    return {'changesPP':changes}


def render_heatmap(p,c):
    d=c['data'];same(d['labels'],d['values'])
    require(all(len(row)==len(d['columns']) for row in d['values']),'heatmap rows must align')
    unit(p,d['units'])
    limit=d['colour_limit'];require(limit>0,'heat scale must be positive')
    left,top,w,h=(340,688,620,414) if p.portrait else (520,523,1200,273)
    cw,ch=w/len(d['columns']),h/len(d['labels'])
    for j,col in enumerate(d['columns']):label(p,f'heat-col-{j}',col,left+j*cw,top-55,cw,40,align='center')
    for i,(name,row) in enumerate(zip(d['labels'],d['values'])):
        text(p,f'heat-row-{i}',name,96,top+i*ch+(ch-44)/2,left-120,44,bold=True,editable=False)
        for j,value in enumerate(numeric(row)):
            require(abs(value)<=limit,'heatmap data exceeds stated colour scale')
            colour=tint(p,value,limit) if p.filled else p.colour('band')
            p.rect(left+j*cw,top+i*ch,cw-5,ch-5,colour)
            cell_text(p,f'heat-value-{i}-{j}',fmt(value,d.get('unit','%'),signed=True),
                      left+j*cw,top+i*ch,cw-5,ch-5,colour,34 if p.portrait else 40)
    caption(p,f'Shared colour scale: {fmt(-limit,d.get("unit","%"))} to {fmt(limit,d.get("unit","%"))}. Read the values as well as the colour.')
    return {'colourDomain':[-limit,limit],'values':d['values']}


def render_diverging(p,c):
    d=c['data'];before=numeric(d['before']);after=numeric(d['after']);same(d['labels'],before,after)
    require(abs(sum(before)-100)<1e-7 and abs(sum(after)-100)<1e-7,'market shares must each sum to 100%')
    changes=[a-b for a,b in zip(after,before)]
    unit(p,'CHANGE IN MARKET SHARE / PERCENTAGE POINTS')
    left,right=(370,860) if p.portrait else (650,1540); top=674 if p.portrait else 530
    spacing=112 if p.portrait else 66;bound=max(1,math.ceil(max(abs(v) for v in changes)))
    middle=(left+right)/2
    p.line([(middle,top-18),(middle,top+spacing*(len(changes)-1)+36)],'axis',3)
    for i,(name,v) in enumerate(zip(d['labels'],changes)):
        y=top+i*spacing
        text(p,f'share-name-{i}',name,96,y-5,left-120,40,bold=True,editable=False)
        if p.filled:
            end=middle+v/bound*(right-left)/2
            p.rect(min(end,middle),y,abs(end-middle),30,'subject' if v>=0 else 'down')
        text(p,f'share-change-{i}',fmt(v,'pp',signed=True),96 if p.portrait else 1580,
             y+46 if p.portrait else y-5,left-120 if p.portrait else 244,42,35,mono=True,bold=True)
    for i,v in enumerate([-bound,0,bound]):
        label(p,f'share-axis-{i}',fmt(v,'pp',signed=True),left+(right-left)*i/2-65,
              1210 if p.portrait else 838,130,40,align='center')
    return {'changesPP':changes,'sumOfChanges':sum(changes)}


def render_pareto(p,c):
    d=c['data'];values=numeric(d['revenue'],positive=True);same(d['labels'],values)
    require(all(a>=b for a,b in zip(values,values[1:])),'Pareto categories must be sorted by size')
    total=sum(values);cum=[v/total*100 for v in cumsum(values)]
    unit(p,'REVENUE: LEFT, $m / CUMULATIVE: RIGHT, %')
    legend(p,[('REVENUE','subject'),('CUMULATIVE SHARE','subject2')])
    box=(232,668,618,378) if p.portrait else (252,523,1388,237)
    high=math.ceil(max(values)/50)*50
    a=Plot(p,'revenue-pareto',(-.5,len(values)-.5),(0,high),box=box)
    a.axes(xticks=list(enumerate(d['labels'])),yticks=[0,high/2,high])
    for i,v in enumerate(values):a.bar(i,v)
    b=Plot(p,'pareto-share',(-.5,len(values)-.5),(0,100),box=box)
    b.line(list(enumerate(cum)),'subject2',5)
    for i,v in enumerate(cum):b.dot(i,v,'subject2')
    for j,v in enumerate([0,50,100]):
        _,y=b.xy(0,v)
        label(p,f'pareto-right-{j}',fmt(v,'%'),876 if p.portrait else 1660,y-15,108 if p.portrait else 164,34)
    summary(p,[('TOP TWO SHARE',fmt(cum[1],'%')),('TOTAL REVENUE',fmt(total,'$m',0))])
    return {'cumulativeShare':cum,'totalRevenue':total}


def render_treemap(p,c):
    d=c['data'];values=numeric(d['revenue'],positive=True);same(d['labels'],values)
    require(len(values)==4,'treemap has four business lines')
    total=sum(values);sizes=values if p.filled else [1]*4
    x,y,w,h=(96,640,888,482) if p.portrait else (96,500,1728,320)
    left_share=sum(sizes[:2])/sum(sizes)
    boxes=[]
    for group in range(2):
        gx=x if group==0 else x+w*left_share
        gw=w*left_share if group==0 else w*(1-left_share)
        frac=sizes[group*2]/sum(sizes[group*2:group*2+2])
        boxes.extend([(gx,y,gw,h*frac),(gx,y+h*frac,gw,h*(1-frac))])
    unit(p,'RECTANGLE AREA = REVENUE / ONE SHARED TOTAL')
    for i,((bx,by,bw,bh),name,value) in enumerate(zip(boxes,d['labels'],values)):
        bg=p.colour(COLOURS[i]) if p.filled else p.colour('band')
        p.rect(bx,by,bw,bh,bg,'structure',sw=2)
        foreground=max((p.colour('ground'),p.colour('structure')),key=lambda col:studio.contrast(col,bg))
        text(p,f'tree-label-{i}',name,bx+20,by+(20 if p.portrait else 16),bw-46,42 if p.portrait else 36,bold=True,background=bg,colour=foreground,editable=False)
        text(p,f'tree-value-{i}',fmt(value/total*100,'%'),bx+20,by+(76 if p.portrait else 60),bw-46,50 if p.portrait else 40,43,
             mono=True,bold=True,background=bg,colour=foreground)
    summary(p,[('TOTAL REVENUE',fmt(total,'$m',0)),('LARGEST SHARE',fmt(max(values)/total*100,'%'))])
    return {'shares':[v/total for v in values],'boxes':boxes,'totalRevenue':total}


def render_mekko(p,c):
    d=c['data'];revenues=numeric(d['revenue'],positive=True);margins=numeric(d['margins'])
    same(d['labels'],revenues,margins);require(len(revenues)==3,'Mekko uses three segments')
    require(all(0<v<100 for v in margins),'Mekko requires positive margins below 100%')
    total=sum(revenues);profit=sum(v*m/100 for v,m in zip(revenues,margins))
    unit(p,'WIDTH = REVENUE / PROFIT AREA = OP. PROFIT')
    legend(p,[('OPERATING COST','rule'),('OPERATING PROFIT','subject')])
    x,y,w,h=(96,704,888,360) if p.portrait else (96,584,1728,216)
    cursor=x
    for i,(name,revenue,margin) in enumerate(zip(d['labels'],revenues,margins)):
        width=w*(revenue/total if p.filled else 1/3)
        profit_h=h*(margin/100 if p.filled else .5)
        p.rect(cursor,y,width,h,'band','structure',sw=2)
        if p.filled:p.rect(cursor,y+h-profit_h,width,profit_h,'subject','structure' if p.ground=='paper' else None,sw=2)
        label(p,f'mekko-name-{i}',name,cursor+8,y-54,width-22,40,align='center')
        text(p,f'mekko-revenue-{i}',fmt(revenue/total*100,'%'),cursor+10,y+35,width-26,45,38,
             mono=True,bold=True,align='center',background='band')
        text(p,f'mekko-margin-{i}',fmt(margin,'%'),cursor+8,y+h-profit_h+2,
             width-22,profit_h-4,34 if p.portrait else 36,mono=True,bold=True,align='center',
             colour='ground',background='subject')
        cursor+=width
    summary(p,[('GROUP MARGIN',fmt(profit/total*100,'%')),('OP. PROFIT',fmt(profit,'$m',0))])
    return {'revenue':total,'operatingProfit':profit,'margin':profit/total*100,
            'areaShareOfProfit':[v*m/100/total for v,m in zip(revenues,margins)]}


def render_frontier(p,c):
    d=c['data'];kind=d['model'];xs=numeric(d['x_values'],positive=True)
    if kind=='price_volume':
        require(min(xs)>d['variable_cost'],'unit price must exceed variable cost')
        ys=[d['fixed_cost']/(v-d['variable_cost']) for v in xs]
        actual_y=d['actual_volume'];actual_x=d['actual_price']
        actual_result=(actual_x-d['variable_cost'])*actual_y-d['fixed_cost']
        result_label='ACTUAL OP. PROFIT';result=fmt(actual_result,'$m')
    elif kind=='cash_turnover':
        ys=[d['sales']/365*v for v in xs]
        actual_x=d['actual_days'];actual_y=d['actual_working_capital']
        actual_result=d['sales']/365*actual_x
        result_label='MODEL CASH TIED UP';result=fmt(actual_result,'$m')
    elif kind=='interest_cover':
        ys=[d['debt']*v/100*d['cover'] for v in xs]
        actual_x=d['actual_rate'];actual_y=d['actual_ebitda']
        actual_result=actual_y/(d['debt']*actual_x/100)
        result_label='ACTUAL COVERAGE';result=fmt(actual_result,'x')
    else:raise ValueError('unknown frontier model')
    unit(p,d['units'])
    legend(p,[('REQUIRED / MODELLED','subject'),('EXAMPLE POINT','subject2')])
    a=Plot(p,'economic-frontier',(min(xs),max(xs)),tuple(d['y_domain']))
    a.axes(xticks=[xs[0],xs[len(xs)//2],xs[-1]],yticks=[a.y0,(a.y0+a.y1)/2,a.y1],
           xformat=lambda v:fmt(v,d['x_unit']),yformat=lambda v:n(v,0))
    a.line(list(zip(xs,ys)));a.dot(actual_x,actual_y,'subject2',r=12)
    summary(p,[(result_label,result),('X AT EXAMPLE',fmt(actual_x,d['x_unit']))])
    return {'frontierX':xs,'frontierY':ys,'actualResult':actual_result,'actualPoint':[actual_x,actual_y]}


def render_funnel(p,c):
    d=c['data'];values=numeric(d['values'],positive=True);same(d['labels'],values)
    require(all(a>=b for a,b in zip(values,values[1:])),'profit funnel stages must not expand')
    unit(p,'SAME PERIOD / $m / WIDTH RELATIVE TO SALES')
    top=676 if p.portrait else 527;spacing=126 if p.portrait else 80
    center=580 if p.portrait else 1110;maxwidth=340 if p.portrait else 740
    for i,(name,v) in enumerate(zip(d['labels'],values)):
        y=top+i*spacing;width=maxwidth*v/values[0] if p.filled else maxwidth
        if p.filled:p.rect(center-width/2,y,width,54,COLOURS[i])
        else:p.rect(center-maxwidth/2,y,maxwidth,54,'band','rule',sw=2)
        text(p,f'funnel-name-{i}',name,96,y+2,260 if p.portrait else 620,48,bold=True,editable=False)
        text(p,f'funnel-value-{i}',fmt(v,'$m',0),790 if p.portrait else 1520,y+2,
             194 if p.portrait else 304,48,36 if p.portrait else 45,mono=True,bold=True,align='right')
    caption(p,'Each stage keeps a smaller share of the same sales base.',y=1210 if p.portrait else 850)
    return {'retainedShares':[v/values[0]*100 for v in values]}


def render_sankey(p,c):
    d=c['data'];sources=numeric(d['sources'],positive=True);uses=numeric(d['uses'],positive=True)
    same(sources,d['source_labels']);same(uses,d['use_labels'])
    require(len(sources)==2 and len(uses)==3,'flow map has two sources and three uses')
    total=sum(sources);require(abs(total-sum(uses))<1e-7,'cash-flow ribbons must conserve dollars')
    unit(p,'CASH SOURCES → POOL → USES / $m')
    scale=(300 if p.portrait else 180)/total
    source_y=[760,1080] if p.portrait else [620,790]
    uses_y=[710,930,1140] if p.portrait else [590,710,822]
    sx,mx,ux=(340,540,720) if p.portrait else (450,920,1450)
    middle_y=900 if p.portrait else 690;middle_top=middle_y-total*scale/2
    label(p,'pool-label','CASH POOL',424 if p.portrait else 740,570 if p.portrait else 470,
          232 if p.portrait else 360,40,align='center')
    text(p,'pool-value',fmt(total,'$m',0),424 if p.portrait else 740,616 if p.portrait else 516,
         232 if p.portrait else 360,42,38,mono=True,bold=True,align='center')
    offset=middle_top
    annotations=[]
    for i,(name,v,y) in enumerate(zip(d['source_labels'],sources,source_y)):
        height=v*scale;top=y-height/2
        if p.filled:
            p.polygon([(sx+18,top),(mx-18,offset),(mx-18,offset+height),(sx+18,top+height)],COLOURS[i],.5)
            p.rect(sx-18,top,36,height,COLOURS[i]);offset+=height
        annotations.append((f'source-{i}',name,v,96,y-44,208 if p.portrait else 314))
    offset=middle_top
    for i,(name,v,y) in enumerate(zip(d['use_labels'],uses,uses_y)):
        height=v*scale;top=y-height/2
        if p.filled:
            p.polygon([(mx+18,offset),(ux-18,top),(ux-18,top+height),(mx+18,offset+height)],COLOURS[i+2],.5)
            p.rect(ux-18,top,36,height,COLOURS[i+2]);offset+=height
        annotations.append((f'use-{i}',name,v,760 if p.portrait else 1502,y-44,224 if p.portrait else 322))
    if p.filled:p.rect(mx-18,middle_top,36,total*scale,'structure')
    else:
        for x in (sx,mx,ux):p.rect(x-18,740 if p.portrait else 650,36,100,'band','rule',sw=2)
    for key,name,value,x,y,w in annotations:
        label(p,key+'-name',name,x,y,w,40)
        text(p,key+'-value',fmt(value,'$m',0),x,y+46,w,40,36,mono=True,bold=True)
    return {'sources':sources,'uses':uses,'total':total,'conservationError':sum(sources)-sum(uses)}


def render_payback(p,c):
    d=c['data'];cash=numeric(d['cash_flows']);require(d['initial_outlay']>0,'positive outlay required')
    cumulative=[-d['initial_outlay']]+cumsum(cash,-d['initial_outlay'])
    unit(p,'UNDISCOUNTED CUMULATIVE CASH / $m')
    lo,hi=padded(cumulative,zero=True)
    a=Plot(p,'payback',(0,len(cash)),(lo,hi))
    a.axes(xticks=[(0,'START'),(len(cash)//2,'YR '+str(len(cash)//2)),(len(cash),'YR '+str(len(cash)))],
           yticks=[-d['initial_outlay'],0,max(0,cumulative[-1])],yformat=lambda v:n(v,0))
    a.reference(y=0);a.line(list(enumerate(cumulative)));a.dot(0,cumulative[0],'down',r=10)
    crossing=next((i for i,v in enumerate(cumulative) if v>=0),None)
    if crossing is not None:a.dot(crossing,cumulative[crossing],'subject2',r=11)
    summary(p,[('PAYBACK YEAR',str(crossing) if crossing is not None else 'NONE'),
               ('CASH AT END',fmt(cumulative[-1],'$m',0))])
    return {'cumulativeCash':cumulative,'firstNonnegativeYear':crossing}


def render_accumulation(p,c):
    d=c['data'];profits=numeric(d['profit']);cash=numeric(d['cash']);same(d['years'],profits,cash)
    diffs=[a-b for a,b in zip(profits,cash)];cumulative=cumsum(diffs)
    unit(p,'PROFIT VS CASH, $m / CUMULATIVE GAP, $m')
    legend(p,[('NET PROFIT','subject'),('OPERATING CASH','subject2')])
    topbox=(232,676,706,170) if p.portrait else (252,522,1476,114)
    bottom=(232,960,706,132) if p.portrait else (252,704,1476,72)
    high=math.ceil(max(profits+cash)/25)*25
    a=Plot(p,'period-profit-cash',(-.5,len(profits)-.5),(0,high),box=topbox)
    a.axes(yticks=[0,high])
    for i,(pr,cf) in enumerate(zip(profits,cash)):
        a.bar(i-.18,pr,width=.3);a.bar(i+.18,cf,width=.3,colour='subject2')
    lo,hi=padded(cumulative,zero=True)
    b=Plot(p,'accumulated-gap',(-.5,len(profits)-.5),(lo,hi),box=bottom)
    b.axes(xticks=[(i,label) for i,label in enumerate(d['years'])],yticks=[lo,hi],yformat=lambda v:n(v,0))
    b.line(list(enumerate(cumulative)),'subject3');b.reference(y=0)
    label(p,'accumulated-label','CUMULATIVE PROFIT MINUS CASH',232 if p.portrait else 252,
          888 if p.portrait else 650,p.w-328 if p.portrait else p.w-348,40)
    caption(p,'Cumulative gap: '+fmt(cumulative[-1],'$m',0)+'. Investigate the cash-flow drivers.',y=1200 if p.portrait else 847)
    return {'annualGap':diffs,'cumulativeGap':cumulative}


def render_vintage(p,c):
    d=c['data'];capex=numeric(d['capex']);life=d['useful_life'];years=d['years'];same(capex,years)
    require(type(life) is int and life>=2,'whole-year useful life required')
    require(min(capex)>=0,'capex cannot be negative')
    layers=[]
    for vintage,v in enumerate(capex):
        layers.append([v/life if vintage<=i<vintage+life else 0 for i in range(len(years))])
    totals=[sum(row[i] for row in layers) for i in range(len(years))]
    unit(p,'STRAIGHT-LINE DEPRECIATION BY VINTAGE / $m')
    legend(p,[(year,COLOURS[i]) for i,year in enumerate(years)])
    high=math.ceil(max(totals)/20)*20
    a=Plot(p,'vintage-depreciation',(-.5,len(years)-.5),(0,high))
    a.axes(xticks=list(enumerate(years)),yticks=[0,high/2,high])
    for i in range(len(years)):
        bottom=0
        for j,row in enumerate(layers):
            if row[i]:a.bar(i,bottom+row[i],base_value=bottom,width=.62,colour=COLOURS[j])
            bottom+=row[i]
    caption(p,'Each capex vintage adds expense while earlier vintages run off.')
    return {'annualDepreciation':totals,'vintageLayers':layers,'usefulLife':life}


def render_intervals(p,c):
    d=c['data'];same(d['labels'],d['low'],d['high']);numeric(d['low']);numeric(d['high'])
    require(all(a<=b for a,b in zip(d['low'],d['high'])),'range endpoints are reversed')
    unit(p,'VALUE PER SHARE / $ / METHODS ON ONE SCALE')
    legend(p,[('MODEL RANGE','subject'),('CURRENT PRICE','subject2')])
    lo,hi=d['domain'];left,right=(360,912) if p.portrait else (600,1550)
    top=702 if p.portrait else 538;spacing=125 if p.portrait else 77
    current=left+(d['current']-lo)/(hi-lo)*(right-left)
    require(lo<=d['current']<=hi,'current price outside comparison scale')
    if p.filled:p.line([(current,top-27),(current,top+spacing*(len(d['labels'])-1)+38)],'subject2',4,dash=True)
    for i,(name,low,high) in enumerate(zip(d['labels'],d['low'],d['high'])):
        require(lo<=low<=high<=hi,'valuation range outside axis')
        y=top+i*spacing
        text(p,f'interval-name-{i}',name,96,y-8,left-120,44,bold=True,editable=False)
        px=lambda v:left+(v-lo)/(hi-lo)*(right-left)
        if p.filled:
            p.line([(px(low),y+10),(px(high),y+10)],'subject',18)
            for point in (low,high):p.line([(px(point),y-10),(px(point),y+30)],'structure',3)
        text(p,f'interval-value-{i}',f'{fmt(low,"$",0)}–{fmt(high,"$",0)}',96 if p.portrait else 1590,
             y+44 if p.portrait else y-10,left-120 if p.portrait else 234,42,34 if p.portrait else 35,mono=True,bold=True)
    for i,value in enumerate([lo,(lo+hi)/2,hi]):
        label(p,f'interval-tick-{i}',fmt(value,'$',0),left+(right-left)*i/2-65,
              1197 if p.portrait else 841,130,40,align='center')
    return {'ranges':list(zip(d['low'],d['high'])),'currentPrice':d['current']}


def render_tornado(p,c):
    d=c['data'];base_inputs={k:d[k] for k in ('fcf','multiple','net_debt','shares')}
    def valuation(inputs):
        require(inputs['shares']>0 and inputs['multiple']>0,'positive shares and multiple required')
        return (inputs['fcf']*inputs['multiple']-inputs['net_debt'])/inputs['shares']
    anchor=valuation(base_inputs);rows=[]
    for driver in d['drivers']:
        require(driver['field'] in base_inputs,'unknown tornado input')
        low=valuation({**base_inputs,driver['field']:driver['low']})
        high=valuation({**base_inputs,driver['field']:driver['high']})
        rows.append((driver['name'],min(low,high),max(low,high)))
    rows.sort(key=lambda row:row[2]-row[1],reverse=True)
    unit(p,'VALUE PER SHARE / $ / ONE INPUT AT A TIME')
    legend(p,[('BELOW BASE','down'),('ABOVE BASE','subject')])
    lo,hi=d['domain'];left,right=(360,912) if p.portrait else (620,1560)
    top=700 if p.portrait else 540;spacing=128 if p.portrait else 80
    px=lambda v:left+(v-lo)/(hi-lo)*(right-left)
    if p.filled:p.line([(px(anchor),top-24),(px(anchor),top+spacing*(len(rows)-1)+35)],'axis',4,dash=True)
    for i,(name,low,high) in enumerate(rows):
        require(lo<=low<=anchor<=high<=hi,'tornado cases must straddle base and fit scale')
        y=top+i*spacing
        text(p,f'tornado-name-{i}',name,96,y-8,left-120,44,bold=True,editable=False)
        if p.filled:
            p.rect(px(low),y,px(anchor)-px(low),30,'down')
            p.rect(px(anchor),y,px(high)-px(anchor),30,'subject')
        text(p,f'tornado-range-{i}',fmt(low,'$')+'–'+fmt(high,'$'),96 if p.portrait else 1590,
             y+45 if p.portrait else y-8,left-120 if p.portrait else 234,42,34 if p.portrait else 34,mono=True,bold=True)
    for i,value in enumerate([lo,anchor,hi]):
        label(p,f'tornado-axis-{i}',fmt(value,'$'),px(value)-65,1200 if p.portrait else 843,130,40,align='center')
    return {'baseValue':anchor,'sortedRanges':rows}


def render_dcf_duration(p,c):
    d=c['data'];cash=numeric(d['fcf'],positive=True);r=d['discount_rate']/100;g=d['terminal_growth']/100
    require(r>g and r>0 and g>-1,'DCF needs discount rate above terminal growth')
    pv=[value/(1+r)**(i+1) for i,value in enumerate(cash)]
    terminal=cash[-1]*(1+g)/(r-g)/(1+r)**len(cash)
    values=pv+[terminal];total=sum(values);shares=[v/total*100 for v in values]
    cumulative=cumsum(shares)
    unit(p,'SHARE OF ENTERPRISE VALUE / % / TV SEPARATE')
    legend(p,[('FCF SHARE','subject'),('TERMINAL','subject3'),('CUMULATIVE','subject2')])
    a=Plot(p,'dcf-duration',(-.5,len(values)-.5),(0,100))
    ticks=[(i,str(i+1) if i<len(cash) else 'TV') for i in range(len(values))]
    a.axes(xticks=ticks,yticks=[0,50,100],yformat=lambda v:fmt(v,'%'))
    for i,value in enumerate(shares):a.bar(i,value,colour='subject3' if i==len(cash) else 'subject')
    a.line(list(enumerate(cumulative)),'subject2',4)
    summary(p,[('TERMINAL VALUE SHARE',fmt(shares[-1],'%')),('ENTERPRISE VALUE',fmt(total,'$m',0))])
    return {'discountedCashFlows':pv,'discountedTerminalValue':terminal,'enterpriseValue':total,'valueShares':shares}


def render_band(p,c):
    d=c['data'];values=numeric(d['multiples'],positive=True);window=d['window'];same(d['dates'],values)
    require(type(window)is int and 3<=window<len(values),'historical band needs prior observations')
    dates=iso_dates(d['dates']);indices=list(range(window,len(values)))
    summaries=[[quantile(values[i-window:i],q) for q in (0,.25,.5,.75,1)] for i in indices]
    xx=[dates[i] for i in indices]
    lo,hi=padded(values)
    unit(p,'P/E / x / BANDS USE PRIOR '+str(window)+' POINTS')
    legend(p,[('MIN–MAX','axis'),('Q1–Q3','subject'),('CURRENT','subject2')])
    a=Plot(p,'historical-bands',(xx[0],xx[-1]),(max(0,math.floor(lo)),math.ceil(hi)))
    a.axes(xticks=[(xx[0],d['dates'][indices[0]][2:7]),(xx[-1],d['dates'][-1][2:7])],
           yticks=[a.y0,(a.y0+a.y1)/2,a.y1],yformat=lambda v:fmt(v,'x'))
    a.area(list(zip(xx,[q[4] for q in summaries])),list(zip(xx,[q[0] for q in summaries])),'axis',.2)
    a.area(list(zip(xx,[q[3] for q in summaries])),list(zip(xx,[q[1] for q in summaries])),'subject',.35)
    a.line(list(zip(xx,[q[2] for q in summaries])),'structure',3,dash=True)
    a.line([(dates[i],values[i]) for i in indices],'subject2',5)
    summary(p,[('LATEST MULTIPLE',fmt(values[-1],'x')),('PRIOR MEDIAN',fmt(summaries[-1][2],'x'))])
    return {'priorWindowQuantiles':summaries,'observedMultiples':[values[i] for i in indices],
            'window':window,'currentExcluded':True}


def render_response(p,c):
    d=c['data'];require(d['eps']>0 and d['price']>0 and d['years']>0,'positive valuation inputs required')
    growths=numeric(d['growth_rates']);multiples=numeric(d['exit_multiples'],positive=True)
    curves=[[(d['eps']*(1+g/100)**d['years']*multiple/d['price'])**(1/d['years'])*100-100
             for g in growths] for multiple in multiples]
    unit(p,'X: EPS GROWTH, % / Y: ANNUAL RETURN, %')
    legend(p,[(f'EXIT {n(v,0)}x',COLOURS[i]) for i,v in enumerate(multiples)])
    lo,hi=padded([value for row in curves for value in row],zero=True)
    a=Plot(p,'valuation-returns',(min(growths),max(growths)),(math.floor(lo/5)*5,math.ceil(hi/5)*5))
    a.axes(xticks=[growths[0],growths[len(growths)//2],growths[-1]],
           yticks=[a.y0,0,a.y1],xformat=lambda v:fmt(v,'%'),yformat=lambda v:fmt(v,'%'))
    a.reference(y=0)
    for i,row in enumerate(curves):a.line(list(zip(growths,row)),COLOURS[i])
    caption(p,f'{d["years"]}-year price-return scenarios. No dividends or probabilities.')
    return {'annualReturnCurves':curves,'exitMultiples':multiples,'growthRates':growths}


def render_maturity_step(p,c):
    d=c['data'];values=numeric(d['principal'],positive=True);same(d['dates'],values)
    dates=iso_dates(d['dates']);start=date.fromisoformat(d['start']).toordinal()
    require(start<dates[0],'maturity start must precede first date')
    total=sum(values);cum=[v/total*100 for v in cumsum(values)]
    points=[(start,0)]+list(zip(dates,cum))
    unit(p,'CUMULATIVE SCHEDULED PRINCIPAL / % OF DEBT')
    a=Plot(p,'maturity-step',(start,dates[-1]),(0,100))
    a.axes(xticks=[(start,d['start'][:4]),(dates[1],d['dates'][1][:4]),(dates[-1],d['dates'][-1][:4])],
           yticks=[0,50,100],yformat=lambda v:fmt(v,'%'))
    a.line(points,step=True)
    for x,y in points:a.dot(x,y,'subject',r=8)
    summary(p,[('FIRST TWO MATURITIES',fmt(sum(values[:2])/total*100,'%')),('SCHEDULED DEBT',fmt(total,'$m',0))])
    return {'cumulativePrincipalPct':cum,'totalPrincipal':total}


def render_refi_vintages(p,c):
    d=c['data'];same(d['amounts'],d['old_rates'],d['maturity_years']);numeric(d['amounts'],positive=True);numeric(d['old_rates'])
    years=d['years'];require(all(a<b for a,b in zip(years,years[1:])),'refinancing years must increase')
    layers=[]
    for amount,rate,maturity in zip(d['amounts'],d['old_rates'],d['maturity_years']):
        layers.append([amount*(d['new_rate'] if year>=maturity else rate)/100 for year in years])
    totals=[sum(row[i] for row in layers) for i in range(len(years))]
    unit(p,'YEAR-END ANNUAL INTEREST RUN RATE / $m')
    legend(p,[(str(year)+' DEBT',COLOURS[i]) for i,year in enumerate(d['maturity_years'])])
    high=math.ceil(max(totals)/10)*10
    a=Plot(p,'refi-vintages',(-.5,len(years)-.5),(0,high))
    a.axes(xticks=list(enumerate([str(y) for y in years])),yticks=[0,high/2,high])
    for i in range(len(years)):
        bottom=0
        for j,row in enumerate(layers):
            a.bar(i,bottom+row[i],base_value=bottom,width=.62,colour=COLOURS[j]);bottom+=row[i]
    summary(p,[('INITIAL INTEREST',fmt(totals[0],'$m')),('FINAL RUN RATE',fmt(totals[-1],'$m'))])
    return {'interestByTranche':layers,'totalAnnualInterest':totals}


def render_coverage(p,c):
    d=c['data'];same(d['periods'],d['inflows'],d['obligations']);numeric(d['inflows']);numeric(d['obligations'])
    require(min(d['inflows']+d['obligations'])>=0 and min(d['cash'],d['facility'])>=0,'funding inputs must be nonnegative')
    sources=[d['cash']+d['facility']+v for v in cumsum(d['inflows'])]
    uses=cumsum(d['obligations'])
    horizontal_rows(p,c,list(zip(d['periods'],sources,uses)),(0,d['axis_max']),
                    unit_label='CUMULATIVE FUNDING / $m / LABEL = GAP',
                    formatter=lambda value:fmt(-value,'$m',signed=True),mode='bullet',
                    labels=('SOURCES','USES'),tick_formatter=lambda value:fmt(value,'$m',0))
    caption(p,'Sources include starting cash, facility and forecast inflows.')
    return {'cumulativeSources':sources,'cumulativeUses':uses,'coverageGap':[a-b for a,b in zip(sources,uses)]}


def render_network(p,c):
    d=c['data'];require(len(d['amounts'])==3,'three disclosed transactions required');numeric(d['amounts'],positive=True)
    unit(p,'SOLID = CASH / DASHED = CONTROL / $m')
    if p.portrait:
        boxes=[(96,638,330,132),(654,638,330,132),(96,1060,330,132),(654,1060,330,132)]
        edges=[([(426,704),(654,704)],(442,632,196,42),(442,722,196,40)),
               ([(426,770),(654,1060)],(510,846,250,42),(510,894,250,40)),
               ([(819,770),(819,1060)],(830,870,154,42),(830,918,154,40))]
        control=[(261,1060),(261,770)];control_box=(96,856,150,70)
    else:
        boxes=[(96,500,400,122),(1424,500,400,122),(96,734,400,122),(1424,734,400,122)]
        edges=[([(496,561),(1424,561)],(710,505,500,40),(710,582,500,40)),
               ([(496,622),(1424,795)],(830,664,380,40),(830,710,380,40)),
               ([(1775,622),(1775,734)],(1440,645,290,40),(1440,688,290,40))]
        control=[(296,734),(296,622)];control_box=(96,652,180,70)
    for i,((x,y,w,h),name,note) in enumerate(zip(boxes,d['nodes'],d['notes'])):
        p.card(x,y,w,h)
        text(p,f'node-{i}',name,x+18,y+18,w-36,44,38,bold=True,background='band',editable=False)
        text(p,f'node-note-{i}',note,x+18,y+77,w-36,40,34 if p.portrait else 28,background='band')
    for i,(points,valuebox,labelbox) in enumerate(edges):
        if p.filled:p.line(points,COLOURS[i],5,arrow=True)
        text(p,f'edge-value-{i}',fmt(d['amounts'][i],'$m',0),*valuebox,36,mono=True,bold=True,align='center')
        text(p,f'edge-label-{i}',d['transactions'][i],*labelbox,34 if p.portrait else 28,
             mono=True,align='center')
    if p.filled:p.line(control,'axis',4,dash=True,arrow=True)
    text(p,'control-label','CONTROL',*control_box,34 if p.portrait else 28,mono=True)
    return {'transactions':list(zip(d['transactions'],d['amounts'])),'arrowsAreEvidenceOf':'disclosed direction only'}


def render_lag_matrix(p,c):
    d=c['data'];same(d['periods'],d['sales'],d['collections'])
    count=len(d['periods']);require(count==4,'collection grid has four periods')
    numeric(d['sales'],positive=True);open_balances=[]
    unit(p,'COLLECTIONS BY SALES COHORT / $m')
    left,top,w,h=(270,690,690,420) if p.portrait else (480,530,1240,276)
    cw,ch=w/(count+1),h/count
    for j,name in enumerate(d['periods']+['OPEN']):
        label(p,f'lag-col-{j}',name,left+j*cw,top-55,cw,40,align='center')
    for i,(period,sales,row) in enumerate(zip(d['periods'],d['sales'],d['collections'])):
        require(len(row)==count,'collections must align with calendar quarters')
        require(all(v is None for v in row[:i]),'cash cannot precede this recognised-sales cohort in this model')
        amounts=numeric(row[i:]);require(min(amounts)>=0 and sum(amounts)<=sales,'collections exceed cohort revenue')
        balance=sales-sum(amounts);open_balances.append(balance)
        label(p,f'lag-row-{i}',period+' SALE' if p.portrait else period+' / '+fmt(sales,'$m',0),
              96,top+i*ch+(15 if p.portrait else 16),left-120,40)
        if p.portrait:text(p,f'lag-sales-{i}',fmt(sales,'$m',0),96,top+i*ch+60,left-120,40,34,mono=True)
        for j,value in enumerate(row+[balance]):
            bg=tint(p,value/sales,1) if p.filled and value is not None else p.colour('band')
            p.rect(left+j*cw,top+i*ch,cw-5,ch-5,bg)
            cell_text(p,f'lag-{i}-{j}','—' if value is None else fmt(value,'$',0),
                      left+j*cw,top+i*ch,cw-5,ch-5,bg,34 if p.portrait else 38,editable=value is not None)
    summary(p,[('RECOGNISED SALES',fmt(sum(d['sales']),'$m',0)),('UNCOLLECTED',fmt(sum(open_balances),'$m',0))])
    return {'openBalances':open_balances,'totalSales':sum(d['sales']),'collected':sum(d['sales'])-sum(open_balances)}


def render_paired_panels(p,c):
    d=c['data'];same(d['labels'],d['first'],d['second']);numeric(d['first']);numeric(d['second'])
    is_event=d.get('event_day') is not None
    if is_event:
        require(d['baseline_day'] in d['x'],'event baseline is missing')
        baseline=d['x'].index(d['baseline_day'])
        require(min(d['first']+d['second'])>0,'price indices must be positive')
        first=[(v/d['first'][baseline]-1)*100 for v in d['first']]
        second=[(v/d['second'][baseline]-1)*100 for v in d['second']]
        delta=[a-b for a,b in zip(first,second)]
    else:
        first=d['first'];second=d['second'];delta=[b-a for a,b in zip(first,second)]
    xx=d.get('x',list(range(len(first))));same(xx,first)
    unit(p,d['units']);legend(p,[(d['series'][0],'subject'),(d['series'][1],'subject2')])
    topbox=(232,663,706,180) if p.portrait else (252,520,1476,111)
    bottom=(232,959,706,133) if p.portrait else (252,704,1476,72)
    lo,hi=padded(first+second,zero=is_event)
    a=Plot(p,'first-panel',(min(xx)-.4,max(xx)+.4),(lo,hi),box=topbox)
    a.axes(yticks=[a.y0,a.y1],yformat=lambda v:n(v,0))
    a.line(list(zip(xx,first)));a.line(list(zip(xx,second)),'subject2')
    bound=max(1,math.ceil(max(abs(v) for v in delta)/5)*5)
    b=Plot(p,'second-panel',(min(xx)-.4,max(xx)+.4),(-bound,0 if max(delta)<=0 else bound),box=bottom)
    choose=range(len(xx)) if len(xx)<=4 else (0,len(xx)//2,len(xx)-1)
    b.axes(xticks=[(xx[i],d['labels'][i]) for i in choose],yticks=[-bound,0]+([bound] if b.y1 else []))
    b.reference(y=0)
    for x,value in zip(xx,delta):b.bar(x,value,width=.62,colour='down' if value<0 else 'subject')
    if is_event:
        a.reference(x=d['event_day'],colour='structure');b.reference(x=d['event_day'],colour='structure')
    label(p,'delta-panel-label',d['delta_label'],232 if p.portrait else 252,
          889 if p.portrait else 650,p.w-328 if p.portrait else p.w-348,40)
    caption(p,d['note'],y=1200 if p.portrait else 847)
    return {'firstSeries':first,'secondSeries':second,'delta':delta,
            'baseline':d.get('baseline_day'),'eventDay':d.get('event_day')}


def render_evidence(p,c):
    d=c['data'];same(d['claims'],d['coverage'])
    require(all(len(row)==len(d['sources']) for row in d['coverage']),'source matrix is not rectangular')
    allowed={'stated':('STATED','subject'),'partial':('PART','subject2'),'silent':('—','band')}
    unit(p,'SOURCE COVERAGE / NO AUTOMATIC VERDICT')
    legend(p,[('STATED','subject'),('PARTIAL','subject2'),('SILENT','band')])
    left,top,w,h=(385,694,575,420) if p.portrait else (650,590,1100,220)
    cw,ch=w/len(d['sources']),h/len(d['claims'])
    for j,source in enumerate(d['sources']):
        label(p,f'evidence-source-{j}',source,left+j*cw,top-55,cw,40,align='center')
    for i,(claim,row) in enumerate(zip(d['claims'],d['coverage'])):
        text(p,f'evidence-claim-{i}',claim,96,top+i*ch+(ch-44)/2,left-120,44,bold=True)
        for j,state in enumerate(row):
            require(state in allowed,'unknown source-coverage state')
            word,ink=allowed[state];bg=p.colour(ink if p.filled else 'band')
            p.rect(left+j*cw,top+i*ch,cw-5,ch-5,bg,'rule',sw=2)
            cell_text(p,f'evidence-{i}-{j}',word,left+j*cw,top+i*ch,cw-5,ch-5,bg,34 if p.portrait else 38)
    caption(p,'A source can repeat a claim without independently proving it.')
    return {'states':d['coverage'],'meaning':'coverage only; not proof, truth or a fraud score'}


DRAW = {
    'underwater':render_drawdown, 'recovery':render_recovery, 'horizons':render_horizons,
    'return_wedge':render_gap_area, 'spells':render_spells, 'ecdf':render_ecdf,
    'return_histogram':render_histogram, 'boxplot':render_boxplot, 'correlation':render_correlation,
    'rolling_risk':render_rolling_risk, 'dumbbell':render_dumbbell, 'rank_bump':render_bump,
    'trajectories':render_trajectory, 'heatmap':render_heatmap, 'share_change':render_diverging,
    'pareto':render_pareto, 'treemap':render_treemap, 'mekko':render_mekko,
    'frontier':render_frontier, 'profit_funnel':render_funnel, 'sankey':render_sankey,
    'payback_path':render_payback, 'cumulative_gap':render_accumulation,
    'depreciation_vintages':render_vintage, 'valuation_ranges':render_intervals,
    'tornado':render_tornado, 'dcf_duration':render_dcf_duration, 'historical_band':render_band,
    'return_response':render_response, 'maturity_step':render_maturity_step,
    'refi_vintages':render_refi_vintages, 'funding_bullets':render_coverage,
    'transaction_network':render_network, 'collection_lag':render_lag_matrix,
    'paired_panels':render_paired_panels, 'source_matrix':render_evidence,
}
