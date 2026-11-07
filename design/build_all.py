#!/usr/bin/env python3
"""Build an unwired, text-free kit-shaped delivery into one output directory."""
from __future__ import annotations
import sys
sys.dont_write_bytecode=True
import argparse
import base64
from copy import deepcopy
from functools import lru_cache
import hashlib
import html
import json
import math
from io import BytesIO
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFont
from pipeline.series import paint
from design import core,data,workbook,motion as motions,longs

HERE=ROOT/'design'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def catalog_items():
    items=json.loads((HERE/'catalog.json').read_text())['plates']
    if (HERE/'longs.json').exists():items+=json.loads((HERE/'longs.json').read_text())['plates']
    return items

def chapter_types():
    known={k for k in json.loads((ROOT/'kit/roles.json').read_text())['chapterTypes'] if not k.startswith('_')}
    if (HERE/'longs.json').exists():known.update(json.loads((HERE/'longs.json').read_text())['chapterTypes'])
    return known

@lru_cache(maxsize=512)
def face(family,size,weight):
    name='ArchivoNarrow[wght].ttf' if family=='Archivo Narrow' else 'CourierPrime-Bold.ttf' if weight>=600 else 'CourierPrime-Regular.ttf'
    font=ImageFont.truetype(str(ROOT/'assets/fonts'/name),size)
    if family=='Archivo Narrow':font.set_variation_by_axes([weight])
    return font

def wrap(value,font,width):
    lines=[];line=''
    for word in str(value).split():
        trial=(line+' '+word).strip()
        if line and font.getlength(trial)>width:lines.append(line);line=word
        else:line=trial
    return lines+[line]

def fit(slot):
    _,_,w,h=slot['box']
    for size in range(int(slot['size']),int(slot['minimum'])-1,-1):
        font=face(slot['font'],size,slot['weight']);lines=wrap(slot['example'],font,w-4)
        boxes=[font.getbbox(line or ' ',anchor='ls') for line in lines];top=min(b[1] for b in boxes);bottom=max(b[3] for b in boxes)
        if len(lines)<=slot.get('maxLines',1000) and max(font.getlength(line) for line in lines)<=w-4 and (len(lines)-1)*size*1.18+bottom-top<=h-2:
            return size,lines,top
    raise ValueError(f'{slot["name"]}: example does not fit the repository font in its published box')

def note_for(item,slot):
    rules=item['definition'].get('fields',{});name=slot['name']
    if item.get('legacyId')=='thesis-tripwires':
        if name.startswith('by-when-'):return 'Writer-defined review date, at most 16 characters. The fact-check does not check this deadline.'
        if name.startswith('limit-') or re.fullmatch(r'value-\d-1',name):return 'Writer-defined line in the sand. The fact-check does not check this limit.'
        if name.startswith('state-'):return 'Computed comparison against the writer limit. Allowed values: HOLDS, BREACHED.'
    for key,rule in rules.items():
        if core.slug(key)==name:return rule.get('instruction','Use supplied research for '+name+'.')
    if name=='title':return 'A concise headline supported by the cited workbook or filing; keep company-specific figures faithful.'
    if name=='takeaway':return 'One conclusion supported by the cited figures and their reporting period.'
    if name=='source':return 'The supplied workbook source, date and filing page; never invent attribution.'
    if name=='label-chapter':return 'The chapter display label chosen for this video by the director; not a baked chapter type.'
    if name=='period':return 'Calculated reporting period and units; change the reporting-label input, not this output.'
    if re.search(r'\d',slot['example']) and core.needs_data(item):return 'Workbook figure or axis label emitted by this plate\'s data renderer from its declared source slots; preserve units and period.'
    return 'Research wording for '+name.replace('-',' ')+'; the default is an editable label, not artwork.'

def sectors_for(item):
    return item.get('sectors',[])

def role_for(slot):
    name=slot['name'];mono=slot['font']=='Courier Prime'
    if name=='title':return 'headline'
    if name=='takeaway':return 'caption'
    if name.startswith('by-when-'):return 'caption'
    if name=='source':return 'source'
    if name=='period' or name.startswith('period-') and mono and slot['weight']==400:return 'period'
    if name=='label-chapter':return 'kicker'
    if slot.get('unitLabel') or name in ('unit','chart-units') or name.startswith('unit-'):return 'unit'
    if name.startswith('legend-'):return 'legend'
    if re.search(r'(?:^|-)(?:x|y|tick|date|year)-\d+$',name) or name.startswith(('tick-','axis-low','axis-high')):return 'tick'
    if 'axis' in name:return 'axis'
    if not mono:return 'statement' if slot['size']>=64 else 'body' if slot['weight']>=600 else 'detail'
    if slot['weight']>=600:return 'huge' if slot['size']>=96 else 'figure' if slot['size']>=64 else 'value'
    return 'label' if not slot['editable'] else 'ref'

def share_roles(scene,slots,roles,audit):
    groups={}
    for raw in scene.slots:groups.setdefault(role_for(raw),[]).append(raw)
    shared={}
    for role,members in groups.items():
        specs=[roles[s['name']] for s in members]
        if len({(s['font'],s['weight']) for s in specs})!=1:raise ValueError('Incompatible typography in shared role '+role)
        spec={**specs[0],'size':min(s['size'] for s in specs),'maxChars':min(slots[s['name']]['maxChars'] for s in members)}
        shared[role]=spec
        for raw in members:
            name=raw['name'];slots[name]['role']=role;slots[name]['colour']=roles[name]['colour']
            size,lines,_=fit({**raw,'size':spec['size']})
            if size!=spec['size']:raise ValueError('Shared type role does not fit '+name)
            slots[name]['authoredLines']=len(lines)
            measured=next(a for a in audit if a['slot']==name);measured.update(role=role,size=size,lines=lines)
    roles.clear();roles.update(shared)

def motion_for(item,slots):
    return motions.standalone(item,slots)

def compile_plate(item,aspect,inks,scale,variant=None):
    if item['drawer']=='longs':return longs.compile_plate(item,aspect,inks,scale,variant)
    scene,analysis=core.assemble(item,aspect);slots={};roles={};examples={};audit=[]
    for raw in scene.slots:
        size,lines,_=fit(raw);name=raw['name'];x,y,w,h=raw['box'];font=face(raw['font'],size,raw['weight'])
        line_capacity=max(1,math.floor(w/max(font.getlength('M'),1)))
        cap=max(len(raw['example']),line_capacity*max(1,len(lines)))
        rules=item['definition'].get('fields',{})
        for old,rule in rules.items():
            if core.slug(old)==name:cap=max(len(raw['example']),int(rule.get('max_chars',cap)))
        if name.startswith('by-when-'):cap=16
        colour=raw['colour']
        if core.contrast(inks[colour],inks[raw['background']])<4.5:
            colour=max(('structure','ground'),key=lambda c:core.contrast(inks[c],inks[raw['background']]))
        if core.contrast(inks[colour],inks[raw['background']])<4.5:raise ValueError('Insufficient text contrast: '+item['key']+'/'+name)
        roles[name]={'font':raw['font'],'size':size,'weight':raw['weight'],'colour':colour,'tracking':'0em','transform':'none','maxChars':cap}
        slots[name]={'x':x,'y':y,'w':w,'h':h,'role':name,'align':raw['align'],'maxChars':cap,
                     'authoredLines':max(1,len(lines)),'fit':'wrap','note':note_for(item,raw)}
        if raw.get('unitLabel'):slots[name]['unitLabel']=True
        if not raw['editable'] and not raw.get('unitLabel') and not re.search(r'\d',raw['example']) and name not in ('label-chapter','period'):
            slots[name]['default']=raw['example']
        examples[name]=raw['example'];audit.append({'slot':name,'font':raw['font'],'weight':raw['weight'],'size':size,'lines':lines})
    share_roles(scene,slots,roles,audit)
    if core.needs_data(item):
        spec=data.recipe(item,aspect,scene);x,y,w,h=spec['nativeBox']
        slots['data-area']={'x':x,'y':y,'w':w,'h':h,'role':'plot-area','align':'left','maxChars':0,'authoredLines':0,'fit':'none',
                            'region':True,'renderer':'design.data.draw','labelRenderer':'design.data.labels','inputSlots':list(spec['bindings']),
                            'uses':sorted(set(scene.primitives)),
                            'note':'Pure Python data drawing from these workbook slots. Its label renderer supplies ticks, dates, units and calculated label positions.','recipe':spec}
        for name,b in spec['bindings'].items():
            if name not in slots:
                slots[name]={'x':x,'y':y,'w':0,'h':0,'role':'control','align':'left','maxChars':b.get('maxChars',max(64,len(b['example']))),
                             'authoredLines':1,'fit':'none','region':True,'inputOnly':True,'renderer':'source_value','note':b['note']}
            else:slots[name]['note']=b['note']
            slots[name]['sourceUnit']=b['unit'];slots[name]['source']=b['source'];examples[name]=b['example']
            if b.get('modelScale',1)!=1:slots[name]['modelScale']=b['modelScale']
            if b.get('sign'):slots[name]['sourceSign']=b['sign']
            if b.get('assumption'):slots[name].update(assumption=True,factCheck=False)
        body={s['name'] for s in scene.slots if s['scope']=='body'}
        for name in body:slots[name]['dataLabel']=True
        if item.get('legacyId')=='thesis-tripwires' and item.get('part')==2:
            for i in range(3):
                current=f'current-{i}' if f'current-{i}'in slots else f'value-{i}-0'
                limit=f'limit-{i}' if f'limit-{i}'in slots else f'value-{i}-1'
                source=spec['bindings'][f'input-rules-{i+1}-current']
                slots[current].update(sourceUnit=source['unit'],source=source['source'],note=source['note'])
                slots[limit].update(sourceUnit=spec['bindings'][f'input-rules-{i+1}-limit']['unit'],source=None,factCheck=False,assumption=True)
                slots[f'by-when-{i+1}'].update(sourceUnit='text',source=None,factCheck=False,assumption=True)
    key=item['key']+'-'+aspect;name=key.split('/',1)[1]
    entry={'key':key,'dir':item['key'].split('/',1)[0],'aspect':aspect,'canvas':[scene.w,scene.h],'exportScale':scale,
           'delivered':[scene.w*scale,scene.h*scale],'ground':'paper','bakedText':False,'playback':'static','fps':0,'frameCount':1,
           'files':{'base':name+'.png','baseIsFrame':True,'frames':[{'file':name+'.png','tag':'','args':{}}]},
           'slots':slots,'slotCount':len(slots),'typeRoles':roles,'purpose':item['purpose'],'caution':item['caution'],
           'chapterTypes':item['chapterTypes'],'sectors':sectors_for(item),'example':examples,'typeAudit':audit}
    motion=motion_for(item,slots)
    if motion:entry['motion']=motion
    if item.get('motion',{}).get('kind')=='watchlist':
        entry['motionAnchors']=[{'move':fx['move'],'slot':fx['slot'],'box':{k:slots[fx['slot']][k] for k in ('x','y','w','h')}} for step in motion['steps'] for fx in step.get('effects',[])]
    nodes=core.clean_nodes(scene.nodes,'frame' if core.needs_data(item) else None)
    return entry,nodes

def resolve(nodes,inks):
    result=deepcopy(nodes)
    for n in result:
        for prop in ('fill','stroke'):
            if prop in n['attrs'] and n['attrs'][prop]!='none':
                value=n['attrs'][prop]
                if value not in inks:raise ValueError('Unknown semantic shape ink '+value)
                n['attrs'][prop]=inks[value]
    return result

def raster(entry,nodes,inks,path):
    image=Image.new('RGBA',tuple(entry['delivered']),inks['ground']);paint(image,resolve(nodes,inks),entry['exportScale'])
    rgb=image.convert('RGB');rgb.save(path);rgb.close();image.close()

def review(entry,nodes,inks,path):
    """Examples stay under --out/review and never enter the source branch."""
    scale=entry['exportScale'];image=Image.new('RGBA',tuple(entry['delivered']),inks['ground']);paint(image,resolve(nodes,inks),scale)
    values=deepcopy(entry['example']);positions={}
    colours={}
    if 'longRecipe' in entry:
        from design import contracts
        prepared=longs.prepare(entry,contracts.example_fill(entry),inks);paint(image,prepared['nodes'],scale)
        values.update(prepared['values']);positions.update(prepared['boxes']);colours=prepared['colours']
    elif 'data-area' in entry['slots']:
        region=entry['slots']['data-area'];source={k:values[k] for k in region['inputSlots']}
        paint(image,data.draw(region,source,inks),scale)
        for label in data.labels(region,source,inks):values[label['slot']]=label['text'];positions[label['slot']]=label['box']
    draw=ImageDraw.Draw(image)
    for name,s in entry['slots'].items():
        if s.get('region') or name not in values:continue
        role=entry['typeRoles'][s['role']];role={**role,'colour':colours.get(name,s.get('colour',role['colour']))};box=positions.get(name,[s[k] for k in ('x','y','w','h')])
        minimum=(30 if entry['aspect']=='9x16' else 24) if 'longRecipe'in entry else (34 if entry['aspect']=='9x16' else 26)
        raw={'name':name,'box':box,'example':values[name],'font':role['font'],'size':role['size'],'weight':role['weight'],'minimum':minimum,
             'maxLines':s.get('maxLinesByAspect',{}).get(entry['aspect'],s.get('maxLines',role.get('maxLines',1000)))}
        size,lines,top=fit(raw);font=face(role['font'],size*scale,role['weight']);x,y,w,h=box
        if role.get('valign')=='middle':
            small=face(role['font'],size,role['weight']);bottom=max(small.getbbox(line or ' ',anchor='ls')[3] for line in lines)
            y+=(h-((len(lines)-1)*size*1.18+bottom-top))/2
        for i,line in enumerate(lines):
            advance=font.getlength(line);tx=x*scale if s['align']=='left' else (x+w)*scale-advance if s['align']=='right' else (x+w/2)*scale-advance/2
            draw.text((tx,(y-top+1+i*size*1.18)*scale),line,font=font,fill=inks[role['colour']],anchor='ls')
    rgb=image.convert('RGB');rgb.save(path);rgb.close();image.close()

def write_json(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def preview_pages(folder,previews):
    groups={}
    for key,file in previews:groups.setdefault(re.sub(r'-(16x9|9x16)$','',key),[]).append((key,file))
    items=list(groups.items());pages=[items[i:i+12] for i in range(0,len(items),12)]
    filenames=['index.html']+[f'gallery-{n+1:02d}.html' for n in range(1,len(pages))]
    css='body{background:#f4f2ea;color:#0b0e16;font:18px/1.4 Arial;margin:24px}main{max-width:1400px;margin:auto}h2{overflow-wrap:anywhere}.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.3164fr);gap:20px}figure{margin:0}img{width:100%;height:auto}article{margin:44px 0}nav{display:flex;flex-wrap:wrap;gap:16px}a{color:inherit}@media(max-width:650px){.pair{grid-template-columns:1fr}.short{max-width:300px;margin:auto}}'
    for page,file in zip(pages,filenames):
        parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>Dennis paper delivery</title><style>'+css+'</style><main><h1>Dennis / paper delivery</h1><p>Filled research examples. Every image on this page is embedded; no JavaScript, fonts or adjacent images needed. Production blanks contain no text or sample data.</p><nav>']
        for n,target in enumerate(filenames,1):parts.append(f'<a href="{target}">Page {n}</a>')
        parts.append('</nav>')
        for stem,layouts in page:
            parts.append('<article><h2>'+html.escape(stem)+'</h2><div class="pair">')
            for key,image_file in layouts:
                short=key.endswith('9x16')
                with Image.open(folder/image_file) as im:
                    rgb=im.convert('RGB');rgb.thumbnail((432,768) if short else (960,540),Image.Resampling.LANCZOS);stream=BytesIO();rgb.save(stream,'WEBP',quality=90,method=4)
                src='data:image/webp;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
                parts.append('<figure class="'+('short' if short else 'long')+'"><img loading="lazy" src="'+src+'" alt="'+html.escape(key)+'"><figcaption>'+('Shorts' if short else 'Longs')+' · <a href="'+html.escape(image_file)+'" download>Full-size PNG</a></figcaption></figure>')
            parts.append('</div></article>')
        (folder/file).write_text(''.join(parts)+'</main></html>')

def build(output,*,ground='paper',scale=2,only=(),check=False,with_review=False):
    if ground!='paper':raise ValueError('This delivery targets the bot paper ground')
    items=catalog_items()
    if only:
        matches=lambda i,k:k in (i['key'],i['key'].split('/')[0]) or k=='round3' and i.get('round')==3 or k==f'part-{i.get("part")}'
        chosen=[i for i in items if any(matches(i,k) for k in only)]
        if not chosen or any(not any(matches(i,k) for i in items) for k in only):raise ValueError('Unknown --only plate/family/part')
        items=chosen
    tokens=json.loads((ROOT/'kit/design-tokens.json').read_text());inks=tokens['hours']['night']['plateInk'][ground]
    vocabulary=chapter_types()
    tables=workbook.schema(ROOT/'templates/dennis_data_template.xlsx')
    rows=[]
    for item in items:
        if any(c not in vocabulary for c in item['chapterTypes']):raise ValueError('Unknown chapter type')
        for aspect in item.get('aspects',('16x9','9x16')):
            for variant in item.get('variants',[None]):
                row=compile_plate(item,aspect,inks,scale,variant)
                region=row[0]['slots'].get('data-area')
                if region:
                    for binding in region['recipe']['bindings'].values():
                        if not binding.get('assumption'):workbook.validate_source(binding['source'],tables)
                if item['drawer']=='longs':
                    for field in item['fields'].values():
                        if field.get('source'):workbook.validate_source(field['source'],tables)
                rows.append((item,*row))
    kit_motion=json.loads((HERE/'kit-motion.json').read_text());published={}
    anchors=json.loads((ROOT/'kit/emit/motion.json').read_text())['anchors']['plates']
    for file in (ROOT/'kit').glob('*/manifest.json'):
        raw=json.loads(file.read_text());table=raw.get('plates',raw.get('assets',{}))
        if isinstance(table,dict):published.update(table)
    for key,recipe in kit_motion['plates'].items():
        if key not in published:raise ValueError('Kit motion key is not published: '+key)
        motions.validate(recipe,published[key]['slots'],anchors[key],published[key]['typeRoles'])
        for move in ('line-draw','highlight'):
            if anchors[key].get(move) and not any(step.get('move')==move for step in recipe['steps']):raise ValueError('Published native move is unused: '+key+'/'+move)
    if check:print(f'PASS: {len(rows)} text-free layouts, workbook sources, explicit units, shared type roles and 104 grouped kit motions');return rows
    output=Path(output).resolve()
    protected=(ROOT/'kit',ROOT/'pipeline',ROOT/'bot',ROOT/'assets/plates',HERE)
    if any(output==p or p in output.parents for p in protected) and not (HERE/'_build'==output or HERE/'_build' in output.parents):raise ValueError('Choose a build directory outside production/source folders')
    output.mkdir(parents=True,exist_ok=True);families={};notes={};preview=[]
    for index,(item,entry,nodes) in enumerate(rows,1):
        family=entry['dir'];folder=output/family;folder.mkdir(exist_ok=True);path=folder/entry['files']['base']
        raster(entry,nodes,inks,path);digest=sha(path);entry['files']['sha256']=digest;entry['files']['frames'][0]['hash']=digest
        entry['filesByHour']={h:deepcopy(entry['files']) for h in ('night','dusk')}
        families.setdefault(family,{})[entry['key']]=entry
        notes[entry['key']]={k:entry[k] for k in ('purpose','caution','chapterTypes','sectors')}
        notes[entry['key']]['chapter_types']=entry['chapterTypes']
        if with_review:
            review_folder=output/'review';review_folder.mkdir(exist_ok=True);example=review_folder/(entry['key'].replace('/','-')+'.png')
            review(entry,nodes,inks,example);preview.append((entry['key'],str(example.relative_to(output/'review'))))
        if index%24==0:print(f'Built {index}/{len(rows)} layouts',flush=True)
    for family,plates in families.items():
        write_json(output/family/'manifest.json',{'family':family,'pack':'dennis-source-proposals-1','integrated':False,'bakedText':False,
                                                'exportScale':scale,'hashAlgo':'sha256','assetCount':len(plates),'plates':plates})
    write_json(output/'roles.fragment.json',{'_note':'Unwired proposals; not installed or merged into kit/roles.fragment.json.',**notes})
    write_json(output/'kit-motion.json',kit_motion)
    write_json(output/'manifest.json',{'pack':'dennis-source-proposals-1','integrated':False,'concepts':len(items),'layouts':len(rows),
                                     'families':list(families),'dataConcepts':sum(core.needs_data(i) or i['drawer']=='longs' and i['model']!='question' for i in items),
                                     'motionConcepts':len({item['key'] for item,e,_ in rows if e.get('motion')}),'kitMotionLayouts':len(kit_motion['plates']),
                                     'sourceSha256':{str(p.relative_to(ROOT)):sha(p) for p in [*HERE.glob('*.py'),*HERE.glob('*.json'),*sorted((HERE/'drawings').glob('*.py')),ROOT/'templates/dennis_data_template.xlsx',ROOT/'kit/emit/motion.json'] if p.name not in ('build_gallery.py','build_preview.py')}})
    if with_review:
        preview_pages(output/'review',preview)
    print(f'Built {len(items)} concepts / {len(rows)} text-free layouts into {output}; nothing installed in the bot.')
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--ground',choices=['paper'],default='paper');parser.add_argument('--scale',type=int,choices=[1,2],default=2)
    parser.add_argument('--only',action='append',default=[]);parser.add_argument('--check',action='store_true');parser.add_argument('--review',action='store_true')
    args=parser.parse_args();build(args.out,ground=args.ground,scale=args.scale,only=args.only,check=args.check,with_review=args.review)

if __name__=='__main__':main()
