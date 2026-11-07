"""Pure scene geometry and slot declarations. No fonts, images, subprocesses or I/O."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import math
import re
from pipeline import series as native_series
from . import sources

INK_NAMES=('ground','band','rule','axis','quiet','structure','subject','subject2','attention','subject3','subject4','subject5','contour','down')
INKS={'paper':{name:name for name in INK_NAMES}}

def slug(value):
    return re.sub(r'[^a-z0-9]+','-',str(value).lower()).strip('-')

def contrast(a,b):
    """WCAG for supplied colors; semantic contrast while authoring slot roles."""
    if a==b:return 1
    if a.startswith('#') and b.startswith('#'):
        def light(value):
            rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
            rgb=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb]
            return sum(c*w for c,w in zip(rgb,(.2126,.7152,.0722)))
        x,y=sorted((light(a),light(b)));return (y+.05)/(x+.05)
    dark={'structure','subject','attention','down'}
    light={'ground','band','subject2','subject3','subject4'}
    if (a in dark and b in light) or (b in dark and a in light):return 10
    if (a=='quiet' and b in light) or (b=='quiet' and a in light):return 6
    return 2

def finite(value):
    if isinstance(value,dict):
        for x in value.values():finite(x)
    elif isinstance(value,(list,tuple)):
        for x in value:finite(x)
    elif type(value) in (int,float) and not math.isfinite(value):raise ValueError('Source figures must be finite')

def node(tag,**attrs):
    finite(attrs)
    return {'tag':tag,'attrs':attrs}

def points_path(points,close=False):
    return 'M'+' L'.join(f'{float(x):.6f},{float(y):.6f}' for x,y in points)+(' Z' if close else '')

class Scene:
    def __init__(self,key,aspect,values,*,inks=None):
        if aspect not in ('16x9','9x16'):raise ValueError('Unknown aspect')
        self.key=key;self.aspect=aspect;self.portrait=aspect=='9x16';self.w,self.h=(1080,1920) if self.portrait else (1920,1080)
        self.filled=True;self.ground='paper';self.ink={name:name for name in INK_NAMES};self.ink.update(inks or {})
        self.slots=[];self.nodes=[];self.regions=[];self.chart_marks=[];self.stages={};self.primitives=[];self.scope='frame'
        self.rect(0,0,self.w,self.h,'ground')
        self.text('title',values['title'],96,260 if self.portrait else 162,self.w-192,155 if self.portrait else 150,
                  size=88 if self.portrait else 100,weight=700,minimum=64)
        self.scope='body'

    def colour(self,name):return self.ink.get(name,name)

    def emit(self,item):
        item['_scope']=self.scope;self.nodes.append(item)

    def rect(self,x,y,w,h,fill='ground',stroke=None,sw=4,dash=False):
        if min(w,h)<0:raise ValueError('Negative shape dimensions')
        if fill in ('subject2','subject3','subject4') and stroke is None:stroke='structure';sw=2
        attrs={'x':x,'y':y,'width':w,'height':h,'fill':self.colour(fill)}
        if stroke:attrs.update({'stroke':self.colour(stroke),'stroke-width':sw})
        if dash:attrs['stroke-dasharray']='14 10'
        self.emit(node('rect',**attrs))

    def circle(self,cx,cy,r,fill='ground',stroke=None,sw=2):
        attrs={'cx':cx,'cy':cy,'r':r,'fill':self.colour(fill)}
        if stroke:attrs.update({'stroke':self.colour(stroke),'stroke-width':sw})
        self.emit(node('circle',**attrs))

    def line(self,points,colour='structure',width=4,dash=False,arrow=False):
        if len(points)<2:return
        attrs={'d':points_path(points),'fill':'none','stroke':self.colour(colour),'stroke-width':width,'stroke-linejoin':'round'}
        if dash:attrs['stroke-dasharray']='12 10'
        if colour in ('subject2','subject3','subject4'):
            self.emit(node('path',**{**attrs,'stroke':self.colour('structure'),'stroke-width':width+4}))
        self.emit(node('path',**attrs))
        if arrow:
            x,y=points[-1];px,py=points[-2];angle=math.atan2(y-py,x-px)
            a=(x-18*math.cos(angle)+10*math.sin(angle),y-18*math.sin(angle)-10*math.cos(angle))
            b=(x-18*math.cos(angle)-10*math.sin(angle),y-18*math.sin(angle)+10*math.cos(angle))
            self.polygon([a,(x,y),b],colour)

    def dot(self,x,y,colour='subject',r=9,hollow=False):
        self.circle(x,y,r,'ground' if hollow else colour,colour if hollow else 'structure',2)

    def polygon(self,points,colour,opacity=1):
        # Paper is flat: a filled, contoured shape rather than alpha blending.
        self.emit(node('path',d=points_path(points,True),fill=self.colour(colour),stroke=self.colour('structure'),**{'stroke-width':2}))

    def series_nodes(self,renderer,nodes,*,colour=None,dash=False,paths_only=False):
        self.primitives.append(renderer)
        for item in nodes:
            if paths_only and item['tag']!='path':continue
            item=deepcopy(item);attrs=item['attrs']
            if colour is not None and attrs.get('fill') not in ('none',None):attrs['fill']=self.colour(colour)
            if attrs.get('fill') not in ('none',None):attrs.update(stroke=self.colour('structure'),**{'stroke-width':2})
            if dash:attrs['stroke-dasharray']='12 10'
            if attrs.get('stroke') in tuple(self.colour(c) for c in ('subject2','subject3','subject4')):
                outline=deepcopy(item);outline['attrs']['stroke']=self.colour('structure');outline['attrs']['stroke-width']=attrs['stroke-width']+4;self.emit(outline)
            self.emit(item)

    def card(self,x,y,w,h,*,fill='band',dash=False):self.rect(x,y,w,h,fill,'structure',dash=dash)

    def text(self,key,value,x,y,w,h,*,size=44,kind='sans',weight=400,colour='structure',align='left',minimum=None,editable=True,background=None):
        key=slug(key)
        if key in ('brand','file'):return
        if any(s['name']==key for s in self.slots):raise ValueError('Duplicate slot '+self.key+'/'+key)
        reverse={v:k for k,v in self.ink.items()}
        colour=reverse.get(colour,colour);background=reverse.get(background,background) or 'ground'
        if colour not in INK_NAMES or background not in INK_NAMES:raise ValueError('Unknown ink role')
        if contrast(self.colour(colour),self.colour(background))<4.5:
            colour=max(('structure','ground'),key=lambda c:contrast(self.colour(c),self.colour(background)))
        self.slots.append({'name':key,'box':[x,y,w,h],'example':str(value),'editable':bool(editable),
                           'font':'Archivo Narrow' if kind=='sans' else 'Courier Prime',
                           'size':size,'weight':weight if kind=='sans' else 700 if kind=='mono-bold' else 400,
                           'colour':colour,'background':background,'align':align,'minimum':minimum or (34 if self.portrait else 26),
                           'scope':self.scope})

    def label(self,key,value,x,y,w,h=44,**kwargs):self.text(key,value,x,y,w,h,kind='mono',editable=False,**kwargs)

    def footer(self,values,*,include_source=True):
        self.scope='frame';y=1312 if self.portrait else 915
        self.line([(96,y-24),(self.w-96,y-24)],'structure',3)
        self.text('takeaway',values['takeaway'],96,y,self.w-192,84 if self.portrait else 60,size=46 if self.portrait else 43,weight=700)
        if include_source:self.text('source',values['source'],96,1402 if self.portrait else 994,self.w-192,76 if self.portrait else 32,
                                    size=34 if self.portrait else 26,kind='mono',colour='quiet')

    @contextmanager
    def stage(self,number):
        first=len(self.nodes);yield
        self.stages.update({i:number for i in range(first,len(self.nodes))})

def needs_data(item):
    if item['drawer'] in ('charts','finance','investigations'):return True
    if item['drawer']=='research':return item['definition']['kind']=='chart'
    if item['drawer']=='stock':
        return any(type(v) in (int,float) for v in item['example'].get('inputs',{}).values())
    return False

def assemble(item,aspect,fields=None,*,inks=None):
    values=deepcopy(item['example'] if fields is None else fields);finite(values)
    definition={**deepcopy(item['definition']),**values,'key':item['key'],'id':item['key']}
    scene=Scene(item['key'],aspect,values,inks=inks);drawer=item['drawer'];analysis={}
    if drawer=='stock':
        analysis=stock.derive(definition);stock.heading(scene,definition);stock.DRAW[definition['layout']](scene,definition,analysis)
    elif drawer=='charts':
        stock.heading(scene,definition);analysis=charts.DRAW[definition['layout']](scene,definition)
    elif drawer in ('chapters','research'):
        chapter=item['chapterTypes'][0].replace('-',' ').upper()
        chapters.label(scene,'chapter',chapter,96,430 if scene.portrait else 344,scene.w-192,55 if scene.portrait else 42)
        if drawer=='chapters':chapters.LAYOUTS[definition['layout']](scene,definition,values)
        elif definition['kind']=='story':research.draw_story(scene,definition,values)
        else:
            analysis=research.derive(definition,values)
            if definition['model'] in ('unbilled','ageing','fees','supplier_finance'):research.draw_composition(scene,definition,values,analysis)
            elif definition['model']=='correction':research.draw_correction(scene,definition,values,analysis)
            else:research.draw_columns(scene,definition,values,analysis)
    else:
        source=finance if drawer=='finance' else investigations
        analysis=source.DRAW[item['legacyId']](scene,values)
    if needs_data(item):sources.apply_labels(item,values,scene)
    scene.footer(values,include_source=not item.get('noSourceLine'));finite(analysis)
    return scene,analysis

def clean_nodes(nodes,scope=None):
    return [{k:v for k,v in n.items() if not k.startswith('_')} for n in nodes if scope is None or n['_scope']==scope]

# Load code once, outside the pure draw calls. Drawing modules only import
# standard-library modules and the semantic helpers defined above.
from .drawings import charts,chapters,finance,investigations,research,stock
