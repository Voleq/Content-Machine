"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
import ast
import math
import operator
from .. import core as studio
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
       ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


FUNCTIONS = {'min': min, 'max': max, 'abs': abs}


def expression(source, values):
    tree = ast.parse(source, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('formula is too complex')

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in BIN:
            return BIN[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS:
            if node.keywords or not 1 <= len(node.args) <= 8:
                raise ValueError('invalid arithmetic function arguments')
            return FUNCTIONS[node.func.id](*[walk(a) for a in node.args])
        if isinstance(node, ast.Compare):
            left = walk(node.left)
            result = True
            for op, right in zip(node.ops, node.comparators):
                if type(op) not in CMP:
                    raise ValueError('unsupported comparison')
                value = walk(right)
                result = result and CMP[type(op)](left, value)
                left = value
            return result
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            items = [bool(walk(n)) for n in node.values]
            return all(items) if isinstance(node.op, ast.And) else any(items)
        raise ValueError(f'unsupported formula syntax: {type(node).__name__}')

    try:
        value = walk(tree)
    except (ZeroDivisionError, OverflowError) as error:
        raise ValueError(f'invalid formula arithmetic: {source}') from error
    if type(value) not in (bool, int, float) or not math.isfinite(value):
        raise ValueError(f'formula must produce a finite number: {source}')
    return value


def derive(concept):
    values = {}
    for name, value in concept['inputs'].items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{concept["key"]}: {name} must be finite and numeric')
        values[name] = value
    for rule in concept.get('constraints', []):
        if expression(rule, values) is not True:
            raise ValueError(f'{concept["key"]}: constraint failed: {rule}')
    metrics = {}
    for item in concept['metrics']:
        key = item['key']
        if key in metrics:
            raise ValueError(f'duplicate metric: {key}')
        value = expression(item['expr'], values)
        if type(value) is bool:
            raise ValueError('display metrics must be numeric, not predicates')
        metrics[key] = {**item, 'value': value}
        values[key] = value
    return metrics


def number(value, places=2):
    if not math.isfinite(value):
        raise ValueError('non-finite display number')
    value = 0 if abs(value) < 1e-9 else value
    return f'{value:,.{places}f}'.rstrip('0').rstrip('.') if places else f'{value:,.0f}'


def formatted(metric):
    value, unit = metric['value'], metric['unit']
    sign = '-' if value < 0 else '+' if metric.get('signed') and value > 0 else ''
    text = number(abs(value), metric.get('places', 2))
    if unit == 'money_m':
        return f'{sign}${text}m'
    if unit == 'money':
        return f'{sign}${text}'
    suffix = {'percent': '%', 'pp': 'pp', 'multiple': 'x', 'shares_m': 'm',
              'months': 'mo', 'number': '', 'count': ''}[unit]
    return sign + text + suffix


def text(p, key, value, x, y, w, h, size=44, *, mono=False, bold=False,
         colour='structure', align='left', background='ground', editable=True):
    if studio.contrast(p.colour(colour), p.colour(background)) < 4.5:
        colour = 'ground' if background == 'structure' else 'structure'
    p.text(key, value, x, y, w, h, size=size,
           kind='mono-bold' if mono and bold else 'mono' if mono else 'sans',
           weight=700 if bold else 400, colour=colour, align=align,
           background=background, editable=editable)


def label(p, key, value, x, y, w, h=44, background='ground', align='left'):
    text(p, key, value, x, y, w, h, 34 if p.portrait else 29,
         mono=True, colour='quiet', background=background, editable=False, align=align)


def stat(p, key, metric, x, y, w, h=90, size=96, background='ground', align='left'):
    text(p, key, formatted(metric), x, y, w, h, size, mono=True, bold=True,
         colour='subject', background=background, align=align)


def heading(p, c):
    text(p, 'period', c['period'], 96, 430 if p.portrait else 344,
         p.w-192, 55 if p.portrait else 42, 34 if p.portrait else 28,
         mono=True, colour='quiet')


def box(p, prefix, metric, x, y, w, h):
    p.card(x, y, w, h)
    label(p, prefix+'-label', metric['label'], x+28, y+20, w-56, background='band')
    if p.portrait:
        short = h < 170
        stat(p, prefix+'-value', metric, x+28, y+(78 if short else 88), 510,
             61 if short else 88, 66 if short else 96, 'band')
        if metric.get('note'):
            text(p, prefix+'-note', metric['note'], x+598, y+(82 if short else 96),
                 260, 58 if short else 88, 34, background='band')
    else:
        stat(p, prefix+'-value', metric, x+28, y+(83 if h < 240 else 91),
             w-56, 88 if h < 240 else 103, 94 if h < 240 else 100, 'band')
        if metric.get('note'):
            text(p, prefix+'-note', metric['note'], x+28, y+h-(45 if h < 240 else 56),
                 w-56, 34 if h < 240 else 45, 28 if h < 240 else 33, background='band')


def result_band(p, metric):
    x, y, w, h = (96, 1062, 888, 188) if p.portrait else (96, 724, 1728, 140)
    p.rect(x, y, w, h, 'structure')
    text(p, 'result-label', metric['label'], x+28, y+21,
         w-56 if p.portrait else 850, 44, 34 if p.portrait else 32,
         mono=True, colour='ground', background='structure', editable=False)
    stat(p, 'result', metric, x+28 if p.portrait else x+990,
         y+83 if p.portrait else y+20, w-56 if p.portrait else 710,
         87 if p.portrait else 102, 106 if p.portrait else 116,
         background='structure')


def formula(p, c, m):
    view = c['view']; items = view['items']
    if len(items) not in (2, 3) or len(view['operators']) != len(items)-1:
        raise ValueError('formula requires two or three input metrics and their operators')
    for i, key in enumerate(items):
        if p.portrait:
            y, h = (510+i*175, 145) if len(items) == 3 else (510+i*250, 196)
            box(p, f'input-{i}', m[key], 96, y, 888, h)
            if i < len(items)-1:
                label(p, f'op-{i}', view['operators'][i], 500, y+h+3, 80, 32, align='center')
        else:
            gap = 120
            w = (1728-gap*(len(items)-1))/len(items)
            x = 96+i*(w+gap)
            box(p, f'input-{i}', m[key], x, 414, w, 224)
            if i < len(items)-1:
                text(p, f'op-{i}', view['operators'][i], x+w+18, 500, 84, 70, 70,
                     mono=True, editable=False, align='center')
    result_band(p, m[view['result']])


def compare(p, c, m):
    view = c['view']
    for i, key in enumerate(view['items']):
        if p.portrait:
            box(p, f'compare-{i}', m[key], 96, 510+i*250, 888, 218)
        else:
            box(p, f'compare-{i}', m[key], 96+i*984, 414, 744, 280)
    result_band(p, m[view['result']])


def ledger(p, c, m):
    keys = c['view']['rows']; total = m[keys[-1]]
    if not 3 <= len(keys) <= 6 or total.get('op') != '=':
        raise ValueError('ledger must have three to six rows ending in =')
    running = 0
    for i, key in enumerate(keys[:-1]):
        item = m[key]; op = item.get('op', '' if i == 0 else '+')
        if op not in ('', '+', '-') or item['unit'] != total['unit']:
            raise ValueError('ledger terms need matching units and + or - operators')
        running += item['value']*(-1 if op == '-' else 1)
    if not math.isclose(running, total['value'], rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError('ledger does not reconcile')
    if not p.portrait:
        p.card(96, 414, 740, 446)
        label(p, 'lead-label', total['label'], 124, 438, 684, background='band')
        stat(p, 'lead-value', total, 124, 538, 684, 150, 135, 'band')
        if total.get('note'):
            text(p, 'lead-note', total['note'], 124, 746, 684, 85, 38, background='band')
    step = min(132, 735/len(keys)) if p.portrait else min(124, 450/len(keys))
    for i, key in enumerate(keys):
        item = m[key]
        x, y, w = (96, 510+i*step, 888) if p.portrait else (940, 414+i*step, 884)
        p.line([(x, y), (x+w, y)], 'structure' if i == len(keys)-1 else 'rule', 3)
        op = item.get('op', '')
        label(p, f'row-label-{i}', (op+' '+item['label']).strip(), x, y+20,
              490 if p.portrait else 500, min(69, step-25))
        stat(p, f'row-value-{i}', item, x+(520 if p.portrait else 536), y+18,
             368 if p.portrait else 348, min(73, step-24), 61 if p.portrait else 65, align='right')


def triptych(p, c, m):
    for i, key in enumerate(c['view']['items']):
        item = m[key]
        if p.portrait:
            box(p, f'card-{i}', item, 96, 510+i*247, 888, 218)
        else:
            x = 96+i*592
            p.card(x, 414, 544, 445)
            label(p, f'card-label-{i}', item['label'], x+28, 438, 488, 76, background='band')
            stat(p, f'card-value-{i}', item, x+28, 549, 488, 125, 111, 'band')
            if item.get('note'):
                text(p, f'card-note-{i}', item['note'], x+28, 723, 488, 110, 42, background='band')


def range_rail(p, c, m):
    v = c['view']
    low, high = m[v['low']]['value'], m[v['high']]['value']
    current = m[v['marker']]['value']
    if not low < high or not low <= current <= high:
        raise ValueError('range marker must be within a nonempty range')
    for key in ['low', 'high', 'marker']:
        if m[v[key]]['unit'] != m[v['marker']]['unit']:
            raise ValueError('range coordinates must use the same units')
    hero = m[v.get('hero', v['marker'])]
    if p.portrait:
        label(p, 'hero-label', hero['label'], 96, 510, 888)
        stat(p, 'hero', hero, 96, 578, 888, 132, 145)
        x, y, width = 96, 820, 888
    else:
        label(p, 'hero-label', hero['label'], 96, 414, 850)
        stat(p, 'hero', hero, 96, 507, 850, 155, 153)
        x, y, width = 1050, 584, 774
    p.line([(x, y), (x+width, y)], 'axis', 10)
    p.line([(x, y-18), (x, y+18)], 'structure', 4)
    p.line([(x+width, y-18), (x+width, y+18)], 'structure', 4)
    points = [(v['marker'], 'subject'), *([(v['boundary'], 'subject2')] if v.get('boundary') else [])]
    for i, (point, colour) in enumerate(points):
        value = m[point]['value']
        if not low <= value <= high or m[point]['unit'] != m[v['marker']]['unit']:
            raise ValueError('boundary must share the range scale')
        if p.filled:
            px = x+width*(value-low)/(high-low)
            p.rect(px-7, y-42, 14, 84, colour, 'structure' if p.ground == 'paper' else None)
        lx, ly = x+i*width/2, 864 if p.portrait else 631
        p.rect(lx, ly+7, 18, 18, colour)
        text(p, f'marker-legend-{i}', m[point]['label'], lx+32, ly, width/2-32,
             34 if p.portrait else 30, 34 if p.portrait else 26,
             mono=True, colour='quiet', editable=False)
    for i, key in enumerate([v['low'], v['high']]):
        bx = 96+i*472 if p.portrait else 1050+i*444
        bw = 416 if p.portrait else 330
        label(p, f'end-label-{i}', m[key]['label'], bx, 900 if p.portrait else 665, bw)
        stat(p, f'end-value-{i}', m[key], bx, 964 if p.portrait else 729, bw, 87, 78)
    for i, key in enumerate(v.get('extras', [])[:2]):
        if p.portrait:
            label(p, f'extra-label-{i}', m[key]['label'], 96, 1146+i*66, 570, 45)
            stat(p, f'extra-{i}', m[key], 692, 1140+i*66, 292, 58, 48, align='right')
        else:
            label(p, f'extra-label-{i}', m[key]['label'], 96, 723+i*80, 570, 48)
            stat(p, f'extra-{i}', m[key], 692, 716+i*80, 254, 63, 54, align='right')


def stack(p, c, m):
    v = c['view']; keys = v['items']
    values = [m[k]['value'] for k in keys]; total = sum(values)
    if not 2 <= len(keys) <= 3 or min(values) < 0 or total <= 0:
        raise ValueError('a composition needs two or three nonnegative parts and a positive total')
    if len({m[k]['unit'] for k in keys}) != 1:
        raise ValueError('composition parts need the same units')
    lead = m[v['result']]
    label(p, 'lead-label', lead['label'], 96, 510 if p.portrait else 414,
          888 if p.portrait else 950)
    stat(p, 'lead', lead, 96 if p.portrait else 1220, 580 if p.portrait else 405,
         888 if p.portrait else 604, 132 if p.portrait else 102, 143 if p.portrait else 110,
         align='left' if p.portrait else 'right')
    y = 758 if p.portrait else 550
    p.rect(96, y, p.w-192, 115, 'band', 'structure', sw=3)
    cursor = 96
    for i, key in enumerate(keys):
        width = (p.w-192)*m[key]['value']/total
        if p.filled and width:
            p.rect(cursor, y, width, 115, ['subject', 'subject2', 'subject3'][i], 'structure' if p.ground == 'paper' else None)
        cursor += width
        x, ly, w = (96, 930+i*106, 888) if p.portrait else (96+i*608, 711, 512)
        label(p, f'part-label-{i}', m[key]['label'], x, ly, 560 if p.portrait else w, 48)
        stat(p, f'part-value-{i}', m[key], x+560 if p.portrait else x,
             ly-4 if p.portrait else ly+70, 328 if p.portrait else w, 79, 68 if p.portrait else 84,
             align='right' if p.portrait else 'left')


def mix(p, c, m):
    v = c['view']
    for row, keys in enumerate([v['before'], v['after']]):
        values = [m[k]['value'] for k in keys]
        if len(values) != 2 or min(values) < 0 or sum(values) <= 0:
            raise ValueError('mix rows need two nonnegative parts and a positive total')
        by = 570+row*270 if p.portrait else 510+row*197
        label(p, f'period-label-{row}', 'BEFORE' if row == 0 else 'AFTER', 96,
              by-59, 600)
        width = 888 if p.portrait else 1150
        p.rect(96, by, width, 90, 'band', 'structure', sw=3)
        cursor = 96
        for i, key in enumerate(keys):
            sw = width*m[key]['value']/sum(values)
            if p.filled and sw:
                p.rect(cursor, by, sw, 90, 'subject' if i == 0 else 'subject2', 'structure' if p.ground == 'paper' else None)
            cursor += sw
        metric = m[v['before_metric'] if row == 0 else v['after_metric']]
        if p.portrait:
            stat(p, f'blend-{row}', metric, 96, by+112, 888, 78, 76)
    for i, name in enumerate(v['legend']):
        lx = 96+i*(444 if p.portrait else 608)
        p.rect(lx, 1086 if p.portrait else 848, 30, 8, 'subject' if i == 0 else 'subject2',
               'structure' if p.ground == 'paper' else None, sw=2)
        label(p, f'legend-{i}', name, lx+48, 1072 if p.portrait else 832, 360, 44)
    result = m[v['result']]
    if p.portrait:
        label(p, 'result-label', result['label'], 96, 1160, 570, 52)
        stat(p, 'result', result, 692, 1154, 292, 85, 73, align='right')
    else:
        for i, key in enumerate([v['result'], v['before_metric'], v['after_metric']]):
            label(p, f'right-label-{i}', m[key]['label'], 1380, 414+i*151, 444, 44)
            stat(p, f'right-value-{i}', m[key], 1380, 470+i*151, 444, 85, 88)


def timeline(p, c, m):
    for i, item in enumerate(c['view']['stages']):
        x, y, w, h = (96, 510+i*247, 888, 218) if p.portrait else (96+i*592, 414, 544, 445)
        p.card(x, y, w, h, fill='ground')
        label(p, f'stage-label-{i}', item['when'], x+28, y+22, w-56, 55)
        stat(p, f'stage-value-{i}', m[item['metric']], x+28, y+91,
             370 if p.portrait else w-56, 87 if p.portrait else 115, 80 if p.portrait else 107)
        text(p, f'stage-note-{i}', item['note'], x+456 if p.portrait else x+28,
             y+88 if p.portrait else y+254, 404 if p.portrait else w-56,
             110 if p.portrait else 164, 38 if p.portrait else 48, bold=True)


def brief(p, c, m):
    for i, item in enumerate(c['view']['cards']):
        x, y, w, h = (96, 510+i*247, 888, 218) if p.portrait else (96+i*592, 414, 544, 445)
        p.card(x, y, w, h, fill='ground')
        p.rect(x, y, 9, h, 'subject' if i == 1 else 'structure')
        label(p, f'card-label-{i}', item['label'], x+28, y+22, w-56, 44)
        text(p, f'card-body-{i}', item['body'], x+28, y+83, w-56,
             119 if p.portrait else 240, 50 if p.portrait else 62, bold=True)
        if not p.portrait and item.get('detail'):
            text(p, f'card-detail-{i}', item['detail'], x+28, y+348, w-56, 79, 33)


def document(p, c, m):
    v = c['view']
    x, y, w, h = (96, 510, 888, 430) if p.portrait else (96, 414, 1050, 448)
    p.card(x, y, w, h, fill='ground')
    label(p, 'document-ref', v['reference'], x+28, y+22, w-56, 55)
    p.rect(x+28, y+101, 8, 220, 'subject')
    text(p, 'document-quote', v['quote'], x+62, y+99, w-96, 226 if p.portrait else 243,
         48 if p.portrait else 63, bold=True)
    text(p, 'document-note', v['note'], x+28, y+350, w-56, 68, 34 if p.portrait else 33, mono=True, colour='quiet')
    for i, item in enumerate(v['checks']):
        sx, sy, sw = (96, 980+i*92, 888) if p.portrait else (1260, 414+i*151, 564)
        label(p, f'check-label-{i}', item['label'], sx, sy, sw, 40)
        text(p, f'check-body-{i}', item['body'], sx, sy+47, sw, 43 if p.portrait else 91,
             41 if p.portrait else 47, bold=True)


def priority(p, c, m):
    if not p.portrait:
        for i, (name, x, w) in enumerate([('ORDER', 96, 570), ('CLAIM', 760, 340), ('RECOVERY', 1160, 340), ('COVERED', 1530, 294)]):
            label(p, f'column-{i}', name, x, 407, w)
    for i, item in enumerate(c['view']['rows']):
        paid = m[item['paid']]; claim = m[item['claim']] if item.get('claim') else None
        if claim and not 0 <= paid['value'] <= claim['value']:
            raise ValueError('recoveries must be within the stated claim')
        if p.portrait:
            y = 510+i*246
            p.card(96, y, 888, 218, fill='ground')
            label(p, f'order-{i}', item['label'], 124, y+22, 832)
            label(p, f'claim-label-{i}', 'CLAIM', 124, y+92, 380, 40)
            label(p, f'paid-label-{i}', 'RECOVERY', 548, y+92, 380, 40)
            if claim:
                stat(p, f'claim-{i}', claim, 124, y+150, 380, 57, 65)
            else:
                text(p, f'claim-{i}', 'Residual', 124, y+150, 380, 57, 48, editable=False)
            stat(p, f'paid-{i}', paid, 548, y+150, 380, 57, 65)
        else:
            y = 479+i*117
            p.line([(96, y-12), (1824, y-12)], 'rule', 2)
            label(p, f'order-{i}', item['label'], 96, y+24, 570, 80)
            if claim:
                stat(p, f'claim-{i}', claim, 760, y+18, 340, 100, 73)
            else:
                text(p, f'claim-{i}', 'Residual', 760, y+30, 340, 80, 48, editable=False)
            stat(p, f'paid-{i}', paid, 1160, y+18, 340, 100, 73)
            if claim and claim['value']:
                text(p, f'coverage-{i}', number(paid['value']/claim['value']*100, 1)+'%',
                     1530, y+32, 294, 67, 46, mono=True, bold=True, align='right')
    total = m[c['view']['result']]
    label(p, 'total-label', total['label'], 96, 1240 if p.portrait else 850, 560, 40)
    stat(p, 'total', total, 700 if p.portrait else 1360, 1235 if p.portrait else 843,
         284 if p.portrait else 464, 46, 42, align='right')


DRAW = {'formula': formula, 'compare': compare, 'ledger': ledger, 'triptych': triptych,
        'range': range_rail, 'threshold': range_rail, 'stack': stack, 'mix': mix,
        'timeline': timeline, 'brief': brief, 'document': document, 'priority': priority}
