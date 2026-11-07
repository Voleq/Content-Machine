"""Manifest-only writer/fill contract for a future adapter. Does not register it."""
from __future__ import annotations
from copy import deepcopy
from . import data

def writer_slots(entry):
    """The writer menu includes source controls, not computed chart labels."""
    if 'longRecipe' in entry:
        from . import longs
        return longs.writer_fields(entry)
    inputs=set(entry['slots'].get('data-area',{}).get('inputSlots',()))
    return {name:slot for name,slot in entry['slots'].items()
            if name in inputs or (not slot.get('region') and (not slot.get('dataLabel') or name=='label-chapter'))}

def writer_menu(entry):
    lines=[entry['key'],entry['purpose'],'Caution: '+entry['caution']]
    for name,slot in writer_slots(entry).items():
        if slot.get('sourceManaged'):continue
        default=' Default: '+slot['default'] if 'default' in slot else ''
        lines.append(f'{name} (max {slot["maxChars"]}): {slot["note"]}{default}')
    return '\n'.join(lines)

def example_fill(entry):
    return {name:entry['example'][name] for name in writer_slots(entry)}

def script_example(entry):
    values=example_fill(entry)
    values={n:v for n,v in values.items() if not entry['slots'][n].get('sourceManaged')}
    if any('|' in v or ']' in v for v in values.values()):raise ValueError('A script value contains a tag delimiter')
    return '[PLATE: '+entry['key']+' | '+' | '.join(name+'='+value for name,value in values.items())+']'

def prepare(entry,values,inks):
    """Validate script strings, calculate shapes/labels, preserve writer wording.

    A future adapter can send nodes to series.paint() and values/boxes to the
    bot's normal type renderer. Source controls are never typeset at 0×0.
    """
    if 'longRecipe' in entry:
        from . import longs
        return longs.prepare(entry,values,inks)
    menu=writer_slots(entry)
    if set(values)-set(menu):raise ValueError('Unknown or computed writer slot')
    result={name:slot['default'] for name,slot in menu.items() if 'default' in slot}
    result.update(deepcopy(values))
    if set(menu)-set(result):raise ValueError('Missing required writer slots')
    for name,value in result.items():
        if not isinstance(value,str) or not value.strip() or value!=value.strip() or len(value)>menu[name]['maxChars'] or any(ord(c)<32 or c in '|]' for c in value):
            raise ValueError('Invalid script text in '+name)
    nodes=[];boxes={}
    if 'data-area' in entry['slots']:
        region=entry['slots']['data-area'];inputs={k:result[k] for k in region['inputSlots']}
        nodes=data.draw(region,inputs,inks)
        computed=data.labels(region,inputs,inks)
        # Chart labels derive from the workbook inputs. The writer retains
        # control of prose and the chapter display label for this video.
        chapter=result.get('label-chapter')
        result.update({label['slot']:label['text'] for label in computed})
        if chapter is not None:result['label-chapter']=chapter
        boxes={label['slot']:label['box'] for label in computed}
    visible={k:v for k,v in result.items() if not entry['slots'][k].get('region')}
    for name,value in visible.items():
        if len(value)>entry['slots'][name]['maxChars']:raise ValueError('Computed label exceeds its published text budget: '+name)
    return {'nodes':nodes,'values':visible,'boxes':boxes}
