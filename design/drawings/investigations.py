"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
import math
def num(v, places=1):
    if not math.isfinite(v):
        raise ValueError('display values must be finite')
    return f'{v:,.{places}f}'.rstrip('0').rstrip('.') if places else f'{v:,.0f}'


def money(v):
    return ('-' if v < 0 else '') + '$' + num(abs(v)) + 'm'


def pct(v):
    v = 0 if abs(v) < 1e-9 else v
    return ('+' if v > 0 else '') + num(v) + '%'


def inputs(d, *keys, positive=(), nonnegative=()):
    out = {}
    for k in keys:
        v = d[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f'{k} must be finite and numeric')
        if k in positive and v <= 0 or k in nonnegative and v < 0:
            raise ValueError(f'{k} is outside its valid range')
        out[k] = float(v)
    return out


def period(p, d):
    p.text('period', d['period'], 96, 430 if p.portrait else 344, p.w-192,
           55 if p.portrait else 42, size=34 if p.portrait else 28, kind='mono', colour='quiet')


def profit_vs_cash(p, d):
    n = inputs(d, 'net_income', 'operating_cash', positive=('net_income',))
    ratio = n['operating_cash']/n['net_income']*100
    gap = n['net_income']-n['operating_cash']
    period(p, d)
    low, high = min(0, n['operating_cash'])*1.15, max(n.values())*1.2
    top, bottom = (744, 1004) if p.portrait else (568, 815)
    yy = lambda v: bottom-(v-low)/(high-low)*(bottom-top)
    zero = yy(0) if p.filled else bottom
    for i, (label, value) in enumerate([('NET INCOME', n['net_income']), ('OPERATING CASH', n['operating_cash'])]):
        x, w = (96+i*472, 416) if p.portrait else (96+i*564, 500)
        p.label(f'metric-label-{i}', label, x, 510 if p.portrait else 408, w, 44,
                size=34 if p.portrait else 29)
        p.text(f'metric-{i}', money(value), x, 580 if p.portrait else 474, w, 91,
               size=88 if p.portrait else 101, kind='mono-bold', colour='subject' if i == 0 else 'structure')
        p.line([(x, zero), (x+w, zero)], 'axis', 3)
        if p.filled and value:
            yv = yy(value)
            p.rect(x+w*.22, min(yv, zero), w*.56, abs(yv-zero), 'subject' if i == 0 else 'structure')
    if p.portrait:
        rows = [('CASH CONVERSION', num(ratio)+'%', 1050), ('PROFIT LESS CASH', money(gap), 1176)]
        for i, (label, value, y) in enumerate(rows):
            p.label(f'summary-label-{i}', label, 96, y+10, 510, 49, size=34)
            p.text(f'summary-{i}', value, 630, y, 354, 85, size=80, kind='mono-bold', align='right')
    else:
        for i, (label, value) in enumerate([('PROFIT LESS CASH', money(gap)), ('CASH CONVERSION', num(ratio)+'%')]):
            y = 414+i*242
            p.label(f'summary-label-{i}', label, 1280, y, 544, 44, size=29, colour='quiet')
            p.text(f'summary-{i}', value, 1280, y+74, 544, 124, size=113, kind='mono-bold')
        p.label('scale-note', 'BARS SHARE A ZERO BASELINE', 96, 846, 1064, 40, size=27, colour='quiet')
    return {'profit_less_operating_cash_m': gap, 'cash_conversion_pct': ratio}


def receivables_growth(p, d):
    keys = ('revenue_before', 'revenue_after', 'receivables_before', 'receivables_after')
    n = inputs(d, *keys, positive=('revenue_before', 'revenue_after', 'receivables_before'),
               nonnegative=('receivables_after',))
    ratios = [n['revenue_after']/n['revenue_before'], n['receivables_after']/n['receivables_before']]
    shares = [n['receivables_before']/n['revenue_before']*100, n['receivables_after']/n['revenue_after']*100]
    maximum = max(1, *ratios)*1.2
    period(p, d)
    for i, (label, ratio) in enumerate(zip(['REVENUE', 'RECEIVABLES'], ratios)):
        if p.portrait:
            y = 510+i*223
            p.label(f'metric-label-{i}', label, 96, y, 560, 44, size=34)
            p.text(f'growth-{i}', pct((ratio-1)*100), 700, y-3, 284, 64, size=61,
                   kind='mono-bold', align='right', colour='subject' if i == 0 else 'subject2')
            for j, (value, tag) in enumerate([(1, 'THEN'), (ratio, 'NOW')]):
                by = y+80+j*58
                p.label(f'bar-label-{i}-{j}', tag, 96, by-3, 146, 38, size=34, colour='quiet')
                p.rect(266, by, 718, 28, 'band')
                if p.filled:
                    p.rect(266, by, 718*value/maximum, 28, 'axis' if j == 0 else 'subject' if i == 0 else 'subject2')
        else:
            x = 96+i*608
            p.label(f'metric-label-{i}', label, x, 414, 512, 42, size=29)
            p.text(f'growth-{i}', pct((ratio-1)*100), x, 481, 512, 103,
                   size=96, kind='mono-bold', colour='subject' if i == 0 else 'subject2')
            p.line([(x, 795), (x+512, 795)], 'axis', 3)
            for j, (value, tag) in enumerate([(1, 'THEN'), (ratio, 'NOW')]):
                bx = x+47+j*264
                if p.filled:
                    bh = 198*value/maximum
                    p.rect(bx, 795-bh, 154, bh, 'axis' if j == 0 else 'subject' if i == 0 else 'subject2')
                p.label(f'bar-label-{i}-{j}', tag, bx-12, 824, 178, 38, size=28,
                        align='center', colour='quiet')
    if p.portrait:
        p.card(96, 1006, 888, 229)
        p.label('ratio-label', 'YEAR-END RECEIVABLES / SALES', 124, 1030, 832, 44, size=34, background='band')
        for i, value in enumerate(shares):
            p.text(f'ratio-{i}', num(value)+'%', 124+i*464, 1120, 368, 86, size=76,
                   kind='mono-bold', background='band')
        p.line([(510, 1161), (570, 1161)], 'structure', 4, arrow=True)
    else:
        p.label('ratio-label', 'RECEIVABLES / SALES', 1312, 414, 512, 42, size=29)
        for i, (label, value) in enumerate(zip(['THEN', 'NOW'], shares)):
            p.label(f'ratio-label-{i}', label, 1312, 477+i*201, 512, 40, size=28, colour='quiet')
            p.text(f'ratio-{i}', num(value)+'%', 1312, 534+i*201, 512, 100, size=91, kind='mono-bold')
    return {'revenue_growth_pct': (ratios[0]-1)*100, 'receivables_growth_pct': (ratios[1]-1)*100,
            'receivables_to_annual_revenue_before_pct': shares[0], 'receivables_to_annual_revenue_after_pct': shares[1]}


def gaap_vs_adjusted(p, d):
    n = inputs(d, 'gaap_profit', 'stock_comp', 'restructuring', nonnegative=('stock_comp', 'restructuring'))
    adjusted = sum(n.values())
    period(p, d)
    if p.portrait:
        for i, (label, value) in enumerate([('GAAP PROFIT', n['gaap_profit']), ('ADJUSTED PROFIT', adjusted)]):
            x = 96+i*472
            p.label(f'profit-label-{i}', label, x, 510, 416, 44, size=34)
            p.text(f'profit-{i}', money(value), x, 580, 416, 100, size=92, kind='mono-bold', colour='subject')
    else:
        p.card(96, 414, 740, 447)
        for i, (label, value) in enumerate([('GAAP PROFIT', n['gaap_profit']), ('ADJUSTED PROFIT', adjusted)]):
            p.label(f'profit-label-{i}', label, 124, 438+i*204, 684, 44, size=29, background='band')
            p.text(f'profit-{i}', money(value), 124, 505+i*204, 684, 120,
                   size=119, kind='mono-bold', colour='subject', background='band')
    rows = [('GAAP PROFIT', n['gaap_profit']), ('+ STOCK COMP', n['stock_comp']),
            ('+ RESTRUCTURING', n['restructuring']), ('= ADJUSTED PROFIT', adjusted)]
    for i, (label, value) in enumerate(rows):
        x, y, w = (96, 776+i*120, 888) if p.portrait else (940, 414+i*125, 884)
        p.line([(x, y), (x+w, y)], 'structure' if i == 3 else 'rule', 3)
        p.label(f'component-label-{i}', label, x, y+20, 490 if p.portrait else 500, 69,
                size=34 if p.portrait else 29)
        p.text(f'component-{i}', money(value), x+520 if p.portrait else x+536, y+20,
               368 if p.portrait else 348, 73, size=61 if p.portrait else 65,
               kind='mono-bold', align='right', colour='subject' if i == 3 else 'structure')
    return {'adjusted_profit_m': adjusted, 'addbacks_m': n['stock_comp']+n['restructuring']}


def related_party(p, d):
    if len(d['entities']) != 2:
        raise ValueError('related-party requires two disclosed entities')
    if p.portrait:
        p.card(96, 430, 888, 170)
        p.text('person', d['person'], 124, 458, 790, 70, size=70, weight=700, background='band')
        p.text('relationship', d['relation'], 124, 545, 790, 42, size=34, kind='mono', background='band')
        p.line([(940, 600), (940, 1067), (842, 1067)], 'subject', 7, arrow=True)
        p.line([(940, 774), (842, 774)], 'subject', 7, arrow=True)
        for i, e in enumerate(d['entities']):
            y = 667+i*293
            p.card(96, y, 746, 240)
            p.text(f'entity-{i}', e['name'], 124, y+24, 684, 72, size=64, weight=700, background='band')
            p.text(f'reference-{i}', e['reference'], 124, y+118, 684, 45, size=34,
                   kind='mono', colour='subject', background='band')
            p.text(f'detail-{i}', e['detail'], 124, y+181, 684, 45, size=38, background='band')
        p.text('disclosure-label', d['disclosure_label'], 96, 1206, 888, 38, size=34, kind='mono', colour='quiet')
        p.text('disclosure', d['disclosure'], 96, 1250, 888, 36, size=34)
    else:
        p.card(620, 340, 680, 156)
        p.text('person', d['person'], 648, 362, 624, 70, size=68, weight=700, align='center', background='band')
        p.text('relationship', d['relation'], 648, 448, 624, 36, size=28, kind='mono', align='center', background='band')
        p.line([(960, 496), (960, 550), (460, 550), (460, 597)], 'subject', 7, arrow=True)
        p.line([(960, 550), (1460, 550), (1460, 597)], 'subject', 7, arrow=True)
        for i, e in enumerate(d['entities']):
            x = 96+i*1000
            p.card(x, 597, 728, 211)
            p.text(f'entity-{i}', e['name'], x+28, 619, 672, 65, size=66, weight=700, background='band')
            p.text(f'reference-{i}', e['reference'], x+28, 708, 672, 38, size=29,
                   kind='mono', colour='subject', background='band')
            p.text(f'detail-{i}', e['detail'], x+28, 759, 672, 38, size=32, background='band')
        p.text('disclosure-label', d['disclosure_label'], 96, 846, 770, 40, size=27, kind='mono', colour='quiet')
        p.text('disclosure', d['disclosure'], 900, 846, 924, 40, size=32, align='right')
    return {}


def restatement(p, d):
    if len(d['rows']) != 3:
        raise ValueError('restatement requires three metrics for the same fiscal year')
    period(p, d)
    changes = []
    if not p.portrait:
        for i, (label, x, w) in enumerate([('METRIC', 96, 570), ('ORIGINAL', 760, 340),
                                         ('RESTATED', 1160, 340), ('CHANGE', 1530, 294)]):
            p.label(f'column-{i}', label, x, 407, w, 44, size=28, colour='quiet')
    for i, row in enumerate(d['rows']):
        n = inputs(row, 'original', 'restated', positive=('original',))
        if row['unit'] not in ('$m', '$'):
            raise ValueError('restatement units must be $m or $')
        delta = (n['restated']/n['original']-1)*100
        values = [money(n[k]) if row['unit'] == '$m' else
                  ('-' if n[k] < 0 else '')+'$'+num(abs(n[k]), 2) for k in ['original', 'restated']]
        changes.append({'metric': row['metric'], 'change_pct': delta})
        if p.portrait:
            y = 510+i*246
            p.card(96, y, 888, 218, fill='ground')
            p.text(f'metric-{i}', row['metric'], 124, y+22, 550, 54, size=48, weight=700)
            p.text(f'change-{i}', pct(delta), 700, y+22, 256, 54, size=43, kind='mono-bold',
                   colour='attention' if delta < 0 else 'subject', align='right')
            for j, (label, value) in enumerate(zip(['ORIGINAL', 'RESTATED'], values)):
                x = 124+j*424
                p.label(f'label-{i}-{j}', label, x, y+92, 380, 40, size=34, colour='quiet')
                p.text(f'value-{i}-{j}', value, x, y+150, 380, 57, size=65, kind='mono-bold')
        else:
            y = 479+i*132
            p.line([(96, y-12), (1824, y-12)], 'rule', 2)
            p.text(f'metric-{i}', row['metric'], 96, y+18, 570, 100, size=58, weight=700)
            for j, value in enumerate(values):
                p.text(f'value-{i}-{j}', value, 760+j*400, y+18, 340, 100, size=73, kind='mono-bold')
            p.text(f'change-{i}', pct(delta), 1530, y+32, 294, 67, size=46,
                   kind='mono-bold', colour='attention' if delta < 0 else 'subject', align='right')
    return {'restatements': changes}


def cash_availability(p, d):
    n = inputs(d, 'total', 'restricted', positive=('total',), nonnegative=('restricted',))
    if n['restricted'] > n['total']:
        raise ValueError('restricted deposits cannot exceed the disclosed total')
    available = n['total']-n['restricted']
    period(p, d)
    p.text('restricted', money(n['restricted']), 96, 510 if p.portrait else 430,
           888 if p.portrait else 850, 200 if p.portrait else 211,
           size=190 if p.portrait else 210, kind='mono-bold', colour='subject2', minimum=100)
    p.label('restricted-label', 'RESTRICTED DEPOSITS', 96, 724 if p.portrait else 680,
            888 if p.portrait else 850, 60, size=42 if p.portrait else 36)
    for i, (label, value) in enumerate([('CASH + DEPOSITS TOTAL', n['total']), ('UNRESTRICTED', available)]):
        x, y, w = (96, 852+i*150, 888) if p.portrait else (1096, 445+i*166, 728)
        p.label(f'cash-label-{i}', label, x, y, w, 47, size=34 if p.portrait else 28, colour='quiet')
        p.text(f'cash-{i}', money(value), x, y+60, w, 78, size=64 if p.portrait else 80,
               kind='mono-bold', colour='subject' if i else 'structure')
    by, bw = (1179 if p.portrait else 785), p.w-192
    p.rect(96, by, bw, 57, 'band', 'axis', sw=3)
    if p.filled and available:
        p.rect(96, by, bw*available/n['total'], 57, 'subject')
    p.label('bar-key', 'UNRESTRICTED / CASH + DEPOSITS', 96, by+68, bw, 36,
            size=34 if p.portrait else 27)
    return {'unrestricted_m': available, 'restricted_share_pct': n['restricted']/n['total']*100}


def claim_response(p, d):
    if len(d['columns']) != 3:
        raise ValueError('claim-response requires a claim, issuer response and filing fact')
    period(p, d)
    for i, c in enumerate(d['columns']):
        x, y, w, h = (96, 510+i*247, 888, 220) if p.portrait else (96+i*592, 428, 544, 429)
        p.card(x, y, w, h, fill='ground')
        p.rect(x, y, 9, h, 'subject' if i == 1 else 'structure')
        p.label(f'label-{i}', c['label'], x+28, y+22, w-56, 42, size=34 if p.portrait else 29)
        p.text(f'body-{i}', c['body'], x+28, y+80, w-56, 78 if p.portrait else 170,
               size=44 if p.portrait else 54, weight=700)
        p.text(f'kind-{i}', c['kind'], x+28, y+h-54 if p.portrait else y+287,
               500 if p.portrait else w-56, 42, size=34 if p.portrait else 28, kind='mono-bold')
        p.text(f'ref-{i}', c['reference'], x+558 if p.portrait else x+28,
               y+h-54 if p.portrait else y+361, 304 if p.portrait else w-56, 42,
               size=34 if p.portrait else 28, kind='mono', colour='quiet', align='right' if p.portrait else 'left')
    return {}


def disclosure_reaction(p, d):
    prices, event = d['prices'], d['event_index']
    if not 4 <= len(prices) <= 8 or type(event) is not int or not 1 <= event <= len(prices)-2:
        raise ValueError('use 4–8 closes, with a disclosure between the first and last observations')
    for v in prices:
        inputs({'price': v}, 'price', positive=('price',))
    before, last = prices[event-1], prices[-1]
    change = (last/before-1)*100
    target = max(prices)/4
    power = 10**math.floor(math.log10(target))
    step = next(m*power for m in [1, 2, 5, 10] if m*power >= target)
    high = math.ceil(max(prices)/step)*step
    period(p, d)
    x, y, w, h = (180, 557, 744, 399) if p.portrait else (210, 466, 978, 344)
    p.label('plot-label', 'ADJUSTED CLOSE / $', 96 if p.portrait else x,
            488 if p.portrait else 405, 888 if p.portrait else 978, 44, size=34 if p.portrait else 29)
    for i in range(round(high/step)+1):
        v = i*step
        py = y+h*(1-v/high)
        p.line([(x, py), (x+w, py)], 'axis', 2, dash=True)
        p.text(f'axis-{i}', num(v), 96, py-17, 66 if p.portrait else 86, 38,
               size=34 if p.portrait else 27, kind='mono', align='right', colour='quiet')
    for i in range(len(prices)):
        px = x+i*w/(len(prices)-1)
        offset = i-event
        p.text(f'date-{i}', ('+' if offset > 0 else '')+str(offset), px-40, y+h+27, 80, 42,
               size=34 if p.portrait else 27, kind='mono', align='center', colour='quiet')
    ex = x+event*w/(len(prices)-1)
    if p.filled:
        p.line([(ex, y), (ex, y+h)], 'attention', 3, dash=True)
        points = [(x+i*w/(len(prices)-1), y+h*(1-v/high)) for i, v in enumerate(prices)]
        p.line(points, 'subject', 9 if p.portrait else 8)
        p.rect(ex-6, points[event][1]-6, 12, 12, 'attention')
    # A text label is placed beside, rather than across, the event line.
    label_x = ex+16 if ex+300 <= x+w else ex-300
    p.text('event-label', 'DISCLOSURE', label_x, y+6, 284, 44,
           size=34 if p.portrait else 28, kind='mono', colour='quiet')
    for i, (label, value) in enumerate([('PRE-EVENT', '$'+num(before)), ('LAST CLOSE', '$'+num(last)), ('CHANGE', pct(change))]):
        sx, sy, sw = (96+i*304, 1060, 280) if p.portrait else (1330, 414+i*158, 494)
        p.label(f'return-label-{i}', label, sx, sy, sw, 44, size=34 if p.portrait else 29, colour='quiet')
        p.text(f'return-{i}', value, sx, sy+63, sw, 80, size=66 if p.portrait else 80,
               kind='mono-bold', colour='down' if i == 2 and change < 0 else 'subject')
    if p.portrait:
        p.label('session-label', 'SESSIONS RELATIVE TO DISCLOSURE', 96, 1230, 888, 44, size=34)
    return {'pre_disclosure_close': before, 'last_close': last, 'price_change_pct': change}


DRAW={'profit-vs-cash':profit_vs_cash, 'receivables-growth':receivables_growth, 'gaap-vs-adjusted':gaap_vs_adjusted, 'related-party':related_party, 'restatement':restatement, 'cash-availability':cash_availability, 'claim-response':claim_response, 'disclosure-reaction':disclosure_reaction}
