"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
import math
def number(value, places=2):
    if not math.isfinite(value):
        raise ValueError('display values must be finite')
    return f'{value:,.{places}f}'.rstrip('0').rstrip('.') if places else f'{value:,.0f}'


def money(value):
    return ('-' if value < 0 else '') + f'${number(abs(value))}m'


def percent(value):
    value = 0 if abs(value) < 1e-9 else value
    return ('+' if value > 0 else '') + number(value, 1) + '%'


def checked(d, *keys, positive=(), nonnegative=()):
    values = {}
    for key in keys:
        value = d[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        if key in positive and value <= 0:
            raise ValueError(f'{key} must be positive')
        if key in nonnegative and value < 0:
            raise ValueError(f'{key} must not be negative')
        values[key] = float(value)
    return values


def period(p, d):
    p.text('period', d['period'], 96, 430 if p.portrait else 344,
           p.w - 192, 55 if p.portrait else 42,
           size=34 if p.portrait else 28, kind='mono', colour='quiet')


def revenue_engine(p, d):
    n = checked(d, 'customers', 'orders_per_customer', 'net_revenue_per_order',
                nonnegative=('customers', 'orders_per_customer', 'net_revenue_per_order'))
    if not n['customers'].is_integer():
        raise ValueError('customers must be a whole count')
    revenue = n['customers'] * n['orders_per_customer'] * n['net_revenue_per_order'] / 1e6
    period(p, d)
    fields = [('ACTIVE CUSTOMERS', number(n['customers'], 0), 'customers'),
              ('ORDERS / CUSTOMER', number(n['orders_per_customer']), 'orders each'),
              ('NET REVENUE / ORDER', '$' + number(n['net_revenue_per_order']), 'per order')]
    for i, (label, value, unit) in enumerate(fields):
        x, y, w, h = (96, 510 + i * 175, 888, 145) if p.portrait else (96 + i * 624, 414, 480, 224)
        p.card(x, y, w, h)
        p.label(f'factor-label-{i}', label, x + 28, y + 18, 560 if p.portrait else w - 56, 42,
                size=34 if p.portrait else 28, colour='quiet', background='band')
        p.text(f'factor-{i}', value, x + 28, y + 76, 510 if p.portrait else w - 56,
               60 if p.portrait else 87, size=66 if p.portrait else 88,
               kind='mono-bold', background='band')
        p.label(f'unit-{i}', unit, x + 598 if p.portrait else x + 28,
                y + 84 if p.portrait else y + 178, 260 if p.portrait else w - 56,
                45 if p.portrait else 36, size=34 if p.portrait else 28, background='band')
        if i < 2:
            p.label(f'multiply-{i}', 'x', 500 if p.portrait else x + 502,
                    y + 148 if p.portrait else y + 86, 80 if p.portrait else 100,
                    27 if p.portrait else 70, size=44 if p.portrait else 72, align='center')
    x, y, w, h = (96, 1062, 888, 188) if p.portrait else (96, 724, 1728, 140)
    p.rect(x, y, w, h, 'structure')
    p.label('revenue-label', 'MODELLED NET REVENUE', x + 28, y + 21,
            w - 56 if p.portrait else 850, 44, size=34 if p.portrait else 32,
            colour='ground', background='structure')
    p.text('revenue', money(revenue), x + 28 if p.portrait else x + 990,
           y + 83 if p.portrait else y + 20, w - 56 if p.portrait else 710,
           87 if p.portrait else 102, size=106 if p.portrait else 116,
           kind='mono-bold', colour='ground', background='structure')
    return {'revenue_m': revenue}


def equity_to_ev(p, d):
    keys = ('equity', 'debt', 'other_claims', 'cash')
    n = checked(d, *keys, nonnegative=keys)
    ev = n['equity'] + n['debt'] + n['other_claims'] - n['cash']
    period(p, d)
    x, y, w, h = (96, 510, 888, 202) if p.portrait else (96, 414, 740, 445)
    p.card(x, y, w, h)
    p.label('ev-label', 'ENTERPRISE VALUE', x + 28, y + 22, w - 56, 44,
            size=34 if p.portrait else 30, background='band')
    p.text('ev', money(ev), x + 28, y + 88 if p.portrait else y + 130,
           w - 56, 96 if p.portrait else 140, size=112 if p.portrait else 133,
           kind='mono-bold', colour='subject', background='band')
    if not p.portrait:
        p.label('ev-explainer', 'EQUITY + OTHER CLAIMS - CASH', x + 28, y + 341,
                w - 56, 66, size=28, background='band')
    rows = [('EQUITY VALUE', n['equity']), ('+ DEBT', n['debt']),
            ('+ PREFERRED + NCI', n['other_claims']), ('- CASH', n['cash']), ('= ENTERPRISE VALUE', ev)]
    for i, (label, value) in enumerate(rows):
        x, y, w = (96, 755 + i * 100, 888) if p.portrait else (940, 414 + i * 92, 884)
        p.line([(x, y), (x + w, y)], 'structure' if i == 4 else 'rule', 4 if i == 4 else 2)
        p.label(f'component-label-{i}', label, x, y + 20, 490 if p.portrait else 500,
                69 if p.portrait else 64, size=34 if p.portrait else 29)
        p.text(f'component-{i}', money(value), x + 520 if p.portrait else x + 536,
               y + 18, 368 if p.portrait else 348, 70 if p.portrait else 66,
               size=56 if p.portrait else 59, kind='mono-bold', align='right',
               colour='subject' if i == 4 else 'structure')
    return {'enterprise_value_m': ev}


def per_share_reality(p, d):
    keys = ('earnings_before', 'earnings_after', 'shares_before', 'shares_after')
    n = checked(d, *keys, positive=keys)
    eps0, eps1 = n['earnings_before'] / n['shares_before'], n['earnings_after'] / n['shares_after']
    ratios = [n['earnings_after'] / n['earnings_before'], n['shares_after'] / n['shares_before'], eps1 / eps0]
    labels = ['TOTAL EARNINGS', 'DILUTED SHARES', 'EARNINGS / SHARE']
    maximum = max(1, *ratios) * 1.2
    period(p, d)
    for i, (label, ratio) in enumerate(zip(labels, ratios)):
        colour = 'down' if i == 2 and ratio < 1 else 'subject'
        if p.portrait:
            y = 510 + i * 247
            p.label(f'metric-{i}', label, 96, y, 560, 44, size=34)
            p.text(f'growth-{i}', percent((ratio - 1) * 100), 700, y - 3, 284, 64,
                   size=61, kind='mono-bold', align='right', colour=colour)
            for j, (value, tag) in enumerate([(1, 'THEN'), (ratio, 'NOW')]):
                by = y + 90 + j * 58
                p.label(f'bar-label-{i}-{j}', tag, 96, by - 3, 146, 38, size=34, colour='quiet')
                p.rect(266, by, 718, 28, 'band')
                if p.filled:
                    p.rect(266, by, 718 * value / maximum, 28, 'axis' if j == 0 else colour)
        else:
            x = 96 + i * 608
            p.label(f'metric-{i}', label, x, 400, 512, 42, size=29)
            p.text(f'growth-{i}', percent((ratio - 1) * 100), x, 466, 512, 95,
                   size=90, kind='mono-bold', colour=colour)
            p.line([(x, 796), (x + 512, 796)], 'axis', 3)
            for j, (value, tag) in enumerate([(1, 'THEN'), (ratio, 'NOW')]):
                bx = x + 47 + j * 264
                if p.filled:
                    bh = 196 * value / maximum
                    p.rect(bx, 796 - bh, 154, bh, 'axis' if j == 0 else colour)
                p.label(f'bar-label-{i}-{j}', tag, bx - 12, 820, 178, 38,
                        size=28, align='center', colour='quiet')
    if p.portrait:
        p.label('index-note', 'EVERY PAIR STARTS AT THE SAME 100', 96, 1230, 888, 44, size=34, colour='quiet')
    return {'eps_before': eps0, 'eps_after': eps1, 'earnings_growth_pct': (ratios[0]-1)*100,
            'share_growth_pct': (ratios[1]-1)*100, 'eps_growth_pct': (ratios[2]-1)*100}


def return_drivers(p, d):
    keys = ('eps_before', 'eps_after', 'pe_before', 'pe_after')
    n = checked(d, *keys, positive=keys)
    price0, price1 = n['eps_before'] * n['pe_before'], n['eps_after'] * n['pe_after']
    earnings_factor = n['eps_after'] / n['eps_before']
    multiple_factor = n['pe_after'] / n['pe_before']
    total_factor = earnings_factor * multiple_factor
    period(p, d)
    pairs = [('EARNINGS / SHARE', '$'+number(n['eps_before']), '$'+number(n['eps_after']), earnings_factor),
             ('P/E MULTIPLE', number(n['pe_before'])+'x', number(n['pe_after'])+'x', multiple_factor)]
    for i, (label, before, after, factor) in enumerate(pairs):
        x, y, w, h = (96, 510 + i * 248, 888, 216) if p.portrait else (96 + i * 984, 414, 744, 282)
        p.card(x, y, w, h)
        p.label(f'factor-label-{i}', label, x + 28, y + 21, w - 56, 44,
                size=34 if p.portrait else 29, background='band')
        p.text(f'before-{i}', before, x + 28, y + 80, (w - 140)/2, 78,
               size=73 if p.portrait else 79, kind='mono-bold', background='band')
        p.text(f'after-{i}', after, x + w/2 + 42, y + 80, w/2 - 70, 78,
               size=73 if p.portrait else 79, kind='mono-bold', align='right', background='band')
        p.line([(x + w/2 - 30, y + 117), (x + w/2 + 30, y + 117)], 'structure', 4, arrow=True)
        p.text(f'change-{i}', percent((factor-1)*100), x + 28, y + 164 if p.portrait else y + 211,
               w - 56, 44 if p.portrait else 53, size=42 if p.portrait else 48,
               kind='mono-bold', colour='subject' if i == 0 else 'structure', background='band')
    x, y, w, h = (96, 1055, 888, 208) if p.portrait else (96, 743, 1728, 126)
    p.rect(x, y, w, h, 'band', 'structure', sw=3)
    equation = f'{number(earnings_factor,2)} x {number(multiple_factor,2)} = {number(total_factor,2)}'
    p.text('equation', equation, x + 28, y + 21, w - 56 if p.portrait else 920, 51,
           size=42 if p.portrait else 44, kind='mono', background='band')
    p.text('price-return', percent((total_factor-1)*100), x + 28 if p.portrait else x + 1132,
           y + 85 if p.portrait else y + 17, w - 56 if p.portrait else 568,
           100 if p.portrait else 92, size=117 if p.portrait else 113,
           kind='mono-bold', colour='down' if total_factor < 1 else 'subject',
           align='left' if p.portrait else 'right', background='band')
    if not p.portrait:
        p.text('price-levels', f'PRICE / ${number(price0)} TO ${number(price1)}', x + 28, y + 80,
               920, 36, size=28, kind='mono', background='band')
    return {'eps_factor': earnings_factor, 'pe_factor': multiple_factor,
            'price_before': price0, 'price_after': price1, 'price_return_pct': (total_factor-1)*100}


def cash_runway(p, d):
    n = checked(d, 'cash', 'monthly_burn', positive=('monthly_burn',), nonnegative=('cash',))
    months = n['cash'] / n['monthly_burn']
    if not math.isfinite(months):
        raise ValueError('calculated cash runway must be finite')
    horizon = max(12, math.ceil(months / 12) * 12)
    period(p, d)
    p.text('runway', number(months,1), 96, 510 if p.portrait else 414,
           888 if p.portrait else 800, 205, size=228 if p.portrait else 240,
           kind='mono-bold', colour='subject', minimum=100)
    p.label('runway-unit', 'MONTHS AT THIS BURN RATE', 96, 747 if p.portrait else 667,
            888 if p.portrait else 800, 57, size=36 if p.portrait else 31)
    for i, (label, value) in enumerate([('CASH', money(n['cash'])), ('MONTHLY NET BURN', money(n['monthly_burn']))]):
        x, y, w = (96 + i * 472, 855, 416) if p.portrait else (1090, 429 + i * 164, 734)
        p.label(f'input-label-{i}', label, x, y, w, 44, size=34 if p.portrait else 29, colour='quiet')
        p.text(f'input-{i}', value, x, y + 67, w, 83, size=76 if p.portrait else 88, kind='mono-bold')
    y = 1090 if p.portrait else 788
    width, gap, count = p.w - 192, 8, 24
    cw = (width - gap * (count-1)) / count
    for i in range(count):
        p.rect(96 + i * (cw + gap), y, cw, 56, 'band', 'axis', sw=2)
        if p.filled:
            fraction = min(1, max(0, months / horizon * count - i))
            if fraction:
                p.rect(96 + i * (cw + gap), y, cw * fraction, 56, 'subject')
    for i in range(5):
        x = 96 + i * width/4
        tx=96 if i==0 else p.w-236 if i==4 else x-70
        align='left' if i==0 else 'right' if i==4 else 'center'
        p.text(f'month-tick-{i}', number(i * horizon/4,1), tx, y + 78,
               140, 44, size=34 if p.portrait else 29, kind='mono', align=align, colour='quiet')
    if p.portrait:
        p.label('rail-unit', 'MONTHS FROM THE REVIEW DATE', 96, 1230, 888, 44, size=34)
    return {'months': months, 'display_horizon_months': horizon}


def benchmark_check(p, d):
    periods, stock, benchmark = d['periods'], d['stock'], d['benchmark']
    if not 3 <= len(periods) <= 6 or len(stock) != len(periods) or len(benchmark) != len(periods):
        raise ValueError('benchmark-check requires 3–6 matching period/stock/benchmark observations')
    for v in [*stock, *benchmark]:
        checked({'index':v},'index',positive=('index',))
    if abs(stock[0]-100)>1e-9 or abs(benchmark[0]-100)>1e-9:
        raise ValueError('both return indices must start at 100')
    sr, br = (stock[-1]/100-1)*100, (benchmark[-1]/100-1)*100
    relative = (stock[-1]/benchmark[-1]-1)*100
    smallest,largest=min(*stock,*benchmark),max(*stock,*benchmark)
    target=max(20,largest-smallest)/3
    power=10**math.floor(math.log10(target))
    step=next(m*power for m in [1,2,5,10] if m*power>=target)
    low=math.floor(smallest/step)*step
    high=math.ceil(largest/step)*step
    if low==smallest: low=max(0,low-step)
    if high==largest: high+=step
    ticks=[low+i*step for i in range(round((high-low)/step)+1)]
    period(p, d)
    x, y, w, h = (180, 555, 744, 399) if p.portrait else (210, 476, 978, 339)
    for i,(name,colour) in enumerate([('STOCK','subject'),('BENCHMARK','subject2')]):
        lx = 96 + i*444 if p.portrait else 210+i*430
        p.rect(lx, 505 if p.portrait else 416, 38, 8, colour)
        p.label(f'legend-{i}', name, lx+56, 488 if p.portrait else 400, 340, 44,
                size=34 if p.portrait else 29)
    for i,value in enumerate(ticks):
        ly = y + h*(1-(value-low)/(high-low))
        p.line([(x,ly),(x+w,ly)],'axis',2,dash=True)
        p.text(f'axis-{i}',number(value,0),96,ly-17,66 if p.portrait else 86,38,
               size=34 if p.portrait else 27,kind='mono',align='right',colour='quiet')
    for i,tag in enumerate(periods):
        lx = x + i*w/(len(periods)-1)
        p.text(f'date-{i}',tag,lx-56,y+h+27,112,42,size=34 if p.portrait else 27,
               kind='mono',align='center',colour='quiet')
    if p.filled:
        for values,colour in [(stock,'subject'),(benchmark,'subject2')]:
            points=[(x+i*w/(len(values)-1),y+h*(1-(v-low)/(high-low))) for i,v in enumerate(values)]
            p.line(points,colour,9 if p.portrait else 8)
            for px,py in points:
                p.rect(px-5,py-5,10,10,colour)
    for i,(name,value,colour) in enumerate([('STOCK',sr,'subject'),('MARKET',br,'subject2'),('RELATIVE',relative,'down' if relative<0 else 'subject')]):
        sx,sy,sw=(96+i*304,1060,280) if p.portrait else (1330,414+i*158,494)
        p.label(f'return-label-{i}',name,sx,sy,sw,44,size=34 if p.portrait else 29,colour='quiet')
        p.text(f'return-{i}',percent(value),sx,sy+63,sw,80,size=66 if p.portrait else 80,kind='mono-bold',colour=colour)
    if p.portrait:
        p.text('point-gap',f'GAP / {percent(sr-br)[:-1]} PERCENTAGE POINTS',96,1230,888,44,size=34,kind='mono')
    return {'stock_return_pct':sr,'benchmark_return_pct':br,'relative_wealth_return_pct':relative,
            'return_gap_percentage_points':sr-br,'axis_min':low,'axis_max':high}


def concentration_stress(p, d):
    n=checked(d,'revenue','customer_revenue','operating_profit','contribution_margin',
              positive=('revenue',),nonnegative=('customer_revenue','operating_profit','contribution_margin'))
    if n['customer_revenue']>n['revenue'] or n['contribution_margin']>1:
        raise ValueError('customer revenue must be within total revenue; contribution margin must be 0–1')
    share=n['customer_revenue']/n['revenue']*100
    loss=n['customer_revenue']*n['contribution_margin']
    stressed=n['operating_profit']-loss
    period(p,d)
    x,y,w,h=(96,510,888,168) if p.portrait else (96,414,640,448)
    p.card(x,y,w,h)
    p.text('concentration',number(share,1)+'%',x+28,y+22 if p.portrait else y+90,
           300 if p.portrait else w-56,100 if p.portrait else 151,
           size=105 if p.portrait else 145,kind='mono-bold',colour='subject',background='band')
    p.label('customer-label','TOP CUSTOMER',x+374 if p.portrait else x+28,
            y+25 if p.portrait else y+25,480 if p.portrait else w-56,44,
            size=34 if p.portrait else 29,background='band')
    p.text('customer-revenue',f'{money(n["customer_revenue"])} OF {money(n["revenue"])}',
           x+374 if p.portrait else x+28,y+91 if p.portrait else y+332,
           480 if p.portrait else w-56,61,size=40 if p.portrait else 43,kind='mono',background='band')
    p.label('plot-label','OPERATING PROFIT / $m',96 if p.portrait else 866,
            714 if p.portrait else 405,888 if p.portrait else 958,44,size=34 if p.portrait else 28)
    low=min(0,stressed)*1.15
    high=max(n['operating_profit'],stressed,1)*1.2
    top,bottom=(884,1105) if p.portrait else (569,806)
    yy=lambda v: bottom-(v-low)/(high-low)*(bottom-top)
    zero=yy(0) if p.filled else bottom
    for i,(label,value) in enumerate([('BEFORE',n['operating_profit']),('STRESSED',stressed)]):
        bx=(124+i*464) if p.portrait else (939+i*550)
        bw=368 if p.portrait else 307
        p.text(f'profit-{i}',money(value),bx,794 if p.portrait else 472,bw,75,
               size=65 if p.portrait else 69,kind='mono-bold',colour='subject' if i==0 else 'down')
        p.line([(bx,zero),(bx+bw,zero)],'structure',3)
        if p.filled and value:
            by=yy(value)
            p.rect(bx+50,min(by,zero),bw-100,abs(by-zero),'subject' if i==0 else 'down','structure')
        p.label(f'profit-label-{i}',label,bx,1131 if p.portrait else 834,bw,44,
                size=34 if p.portrait else 29,align='center')
    p.text('stress-assumption',f'ASSUMED CONTRIBUTION MARGIN / {number(n["contribution_margin"]*100,1)}%',
           96 if p.portrait else 124,1228 if p.portrait else 680,
           888 if p.portrait else 584,44 if p.portrait else 60,
           size=34 if p.portrait else 28,kind='mono',colour='quiet',
           background='ground' if p.portrait else 'band')
    return {'customer_share_pct':share,'lost_contribution_m':loss,'stressed_operating_profit_m':stressed}


def thesis_tripwires(p,d):
    rules=d['rules']
    if len(rules)!=3:
        raise ValueError('thesis-tripwires needs exactly three rules')
    period(p,d)
    results=[]
    if not p.portrait:
        for i,(name,x,w) in enumerate([('METRIC',96,570),('CURRENT',736,290),('LIMIT',1080,330),('STATE',1460,364)]):
            p.label(f'column-{i}',name,x,407,w,44,size=28,colour='quiet')
    for i,r in enumerate(rules):
        n=checked(r,'current','limit')
        if r['operator'] not in ('<=','>=') or r['unit'] not in ('%','x','$m',''):
            raise ValueError('rules support <= or >= and units %, x, $m or empty')
        holds=n['current']<=n['limit'] if r['operator']=='<=' else n['current']>=n['limit']
        state='HOLDS' if holds else 'BREACHED'
        current=money(n['current']) if r['unit']=='$m' else number(n['current'])+r['unit']
        limit_value=money(n['limit']) if r['unit']=='$m' else number(n['limit'])+r['unit']
        limit=r['operator']+' '+limit_value
        if p.portrait:
            y=510+i*246
            p.card(96,y,888,218,fill='ground')
            p.text(f'metric-{i}',r['metric'],124,y+22,490 if 'by_when'in r else 832,54,size=47,weight=700)
            if 'by_when'in r:p.text(f'by-when-{i+1}',r['by_when'],640,y+26,316,50,size=40,weight=700,colour='quiet',align='right')
            for j,(name,value) in enumerate([('CURRENT',current),('LIMIT',limit)]):
                x=124+j*316
                p.label(f'label-{i}-{j}',name,x,y+92,280,40,size=34,colour='quiet')
                p.text(f'value-{i}-{j}',value,x,y+150,272 if j==0 else 256,56,
                       size=57 if j==0 else 45,kind='mono-bold')
            p.rect(736,y+118,220,72,('structure' if holds else 'attention') if p.filled else 'band',
                   None if p.filled else 'structure')
            p.text(f'state-{i}',state,748,y+137,196,40,size=34,kind='mono-bold',colour='ground',
                   align='center',background='structure' if holds else 'attention')
        else:
            y=479+i*132
            p.line([(96,y-12),(1824,y-12)],'rule',2)
            p.text(f'metric-{i}',r['metric'],96,y+18,570,100,size=56,weight=700)
            p.text(f'current-{i}',current,736,y+18,290,100,size=78,kind='mono-bold')
            p.text(f'limit-{i}',limit,1080,y+26,330,80,size=53,kind='mono-bold')
            p.text(f'state-{i}',state,1460,y+36,364,61,size=36,kind='mono-bold',
                   colour='structure' if holds else 'attention')
            if 'by_when'in r:p.text(f'by-when-{i+1}',r['by_when'],96,y+78,570,44,size=40,weight=700,colour='quiet')
        results.append({'metric':r['metric'],'holds':holds})
    return {'rules':results}


DRAW={'revenue-engine':revenue_engine, 'equity-to-ev':equity_to_ev, 'per-share-reality':per_share_reality, 'return-drivers':return_drivers, 'cash-runway':cash_runway, 'benchmark-check':benchmark_check, 'concentration-stress':concentration_stress, 'thesis-tripwires':thesis_tripwires}
