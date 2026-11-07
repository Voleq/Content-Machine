"""Grouped, untimed ideas over published slots; no player or bot registration."""
from __future__ import annotations
from copy import deepcopy

def members(step):
    return [step['slot'],*step.get('includeSlots',[])]

def validate(recipe,slots,anchors=None,type_roles=None):
    steps=recipe['steps']
    if not 2<=len(steps)<=6:raise ValueError('Motion needs two to six genuine ideas')
    seen=set()
    for step in steps:
        group=members(step)
        if len(set(group))!=len(group) or seen.intersection(group):raise ValueError('A motion group repeats a slot')
        seen.update(group)
        if not set(group)<=slots.keys():raise ValueError('Motion uses an unpublished slot')
        cue=step.get('cueSlot')
        if cue is not None:
            slot=slots[cue]
            typed=slot['role'] in type_roles if type_roles is not None else not slot.get('region')
            if cue not in group or not typed or any(slot.get(p) for p in ('inputOnly','renderer','container','overlay','control')):raise ValueError('A spoken cue must be visible text in its idea')
            role=slot['role'].lower()
            if any(x in role for x in ('axis','tick','legend','unit','period','source','kicker')):raise ValueError('Chart furniture cannot be a spoken cue')
        if 'move' in step:
            anchor=(anchors or {}).get(step['move'])
            if not anchor or anchor.get('slot')!=step['slot']:raise ValueError('Native move has no published anchor for this slot')
            if not set(anchor.get('also',[]))<=set(group):raise ValueError('Native move companion regions are missing')
    expected={n for n,s in slots.items() if not s.get('inputOnly') and not s.get('control') and s['role']!='control'}
    if seen!=expected:raise ValueError('Motion must group every visible slot exactly once')
    for proposal in recipe.get('optionalMoves',[]):
        anchor=(anchors or {}).get(proposal['move'])
        if not anchor or anchor.get('slot')!=proposal['slot']:raise ValueError('Optional move has no published anchor')
        if proposal['move']=='count-up' and (proposal.get('enabled') is not False or proposal.get('decisionBy')!='Valentin' or proposal.get('requiresNumericValue') is not True):
            raise ValueError('Count-up is reserved for Valentin and a numeric fill')

def standalone(item,slots):
    if 'motion' not in item:return None
    visible={n:s for n,s in slots.items() if not s.get('inputOnly')}
    if item['motion'].get('kind')=='watchlist':
        steps=[{'slot':'title','action':'appear','cueSlot':'title'}]
        for i in range(3):
            current=f'current-{i}' if f'current-{i}'in slots else f'value-{i}-0'
            limit=f'limit-{i}' if f'limit-{i}'in slots else f'value-{i}-1'
            names=[f'metric-{i}',current,limit,f'state-{i}',f'by-when-{i+1}']
            if i==2:names.append('takeaway')
            steps.append({'slot':'data-area' if i==0 else names[0],'includeSlots':names if i==0 else names[1:],'action':'clip-in' if i==0 else 'appear','cueSlot':f'metric-{i}',
                          'effects':[{'move':'highlight','slot':limit,'cueSlot':limit}]})
        used={n for s in steps for n in members(s)};steps[1]['includeSlots'].extend(n for n in visible if n not in used)
        result={'steps':steps};validate(result,visible);return result
    ideas=deepcopy(item['motion']['ideas'])
    if 'data-area' in visible:
        furniture={'tick','axis','legend','unit','period'}
        ideas=[[n for n in group if visible[n]['role'] not in furniture] for group in ideas]
    steps=[{'slot':'title','action':'appear','cueSlot':'title'}]
    for group in ideas:
        steps.append({'slot':group[0],'includeSlots':group[1:],'action':'appear','cueSlot':group[0]})
    steps.append({'slot':'takeaway','action':'appear','cueSlot':'takeaway'})
    # All context belongs to one idea. In charts that is the data reveal,
    # including axes, ticks, units, legends and non-focus data labels.
    assigned={n for step in steps for n in members(step)}
    context=[n for n in visible if n not in assigned]
    if 'data-area' in visible:
        first=steps[1]
        if first['slot']=='chart-caption':
            steps.insert(1,{'slot':'data-area','action':'clip-in','direction':'left','includeSlots':[n for n in context if n!='data-area']})
        else:
            primary=first['slot']
            first.update(slot='data-area',action='clip-in',direction='left',includeSlots=[primary,*first['includeSlots'],*[n for n in context if n!='data-area']])
    else:steps[0]['includeSlots']=context
    result={'steps':steps}
    validate(result,visible)
    return result
