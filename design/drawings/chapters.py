"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
from .. import core as studio
def label(p,key,value,x,y,w,h=42,*,background='ground',align='left'):
    p.text('label-'+key,value,x,y,w,h,size=34 if p.portrait else 28,kind='mono',
           colour='quiet' if background!='structure' else 'ground',background=background,
           align=align,editable=False)


def content(p,definition,values,key,x,y,w,h,*,size=56,background='ground',colour='structure'):
    p.text(key,values[key],x,y,w,h,size=size,kind='sans',weight=700,
           background=background,colour=colour)


def panel(p,d,values,key,x,y,w,h,*,fill='band',size=56,dash=False):
    p.card(x,y,w,h,fill=fill,dash=dash)
    label(p,key,d['fields'][key]['label'],x+24,y+18,w-48,background=fill)
    content(p,d,values,key,x+24,y+80,w-48,h-102,size=size,background=fill)


def note(p,d,values,key,*,y=None):
    y=y if y is not None else (1098 if p.portrait else 746)
    h=154 if p.portrait else 130
    p.rect(96,y,p.w-192,h,'structure')
    label(p,key,d['fields'][key]['label'],120,y+14,p.w-240,38,background='structure')
    content(p,d,values,key,120,y+66,p.w-240,h-78,size=44 if p.portrait else 46,
            background='structure',colour='ground')


def pair(p,d,v,keys,*,top=None,height=None):
    top=top if top is not None else (542 if p.portrait else 438)
    height=height if height is not None else (238 if p.portrait else 270)
    if p.portrait:
        for i,key in enumerate(keys):panel(p,d,v,key,96,top+i*(height+28),888,height)
    else:
        for i,key in enumerate(keys):panel(p,d,v,key,96+i*888,top,840,height,size=58)


def draw_fold(p,d,v):
    a,b,c=list(d['fields'])
    panel(p,d,v,a,96,542 if p.portrait else 438,p.w-192,238 if p.portrait else 180,size=67)
    if p.portrait:
        p.rect(128,806,856,218,'ground','structure',sw=3)
        label(p,b,d['fields'][b]['label'],152,824,808)
        content(p,d,v,b,152,884,808,114,size=54)
        p.line([(144,784),(144,810),(174,810)],'axis',4)
    else:
        p.rect(240,646,1584,94,'ground','structure',sw=3)
        label(p,b,d['fields'][b]['label'],264,665,430,52)
        content(p,d,v,b,740,664,1060,54,size=44)
        p.line([(190,622),(190,692),(228,692)],'axis',4)
    note(p,d,v,c)


def draw_ticket(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,190,size=70)
        p.line([(112,754),(968,754)],'axis',3,dash=True)
        label(p,b,d['fields'][b]['label'],120,790,840)
        content(p,d,v,b,120,856,840,184,size=67)
    else:
        panel(p,d,v,a,96,438,530,270,size=88)
        p.line([(662,448),(662,696)],'axis',3,dash=True)
        label(p,b,d['fields'][b]['label'],710,446,1114)
        content(p,d,v,b,710,512,1114,174,size=73)
    note(p,d,v,c)


def draw_stack(p,d,v):
    keys=list(d['fields'])
    for i,key in enumerate(keys):
        y=(542+i*239) if p.portrait else (438+i*144)
        if p.portrait:panel(p,d,v,key,96,y,888,210,size=54)
        else:
            p.line([(96,y),(1824,y)],'rule',2)
            label(p,key,d['fields'][key]['label'],96,y+21,450,70)
            content(p,d,v,key,610,y+18,1214,100,size=57)


def draw_roles(p,d,v):
    if p.portrait:
        for i,key in enumerate(d['fields']):
            y=542+i*239
            panel(p,d,v,key,96,y,888,210,size=53)
            p.rect(930,y+20,26,26,'ground','structure',sw=2)
    else:
        for i,key in enumerate(d['fields']):
            x=96+i*592
            panel(p,d,v,key,x,456,544,390,size=57)
            p.rect(x+478,476,38,38,'ground','structure',sw=2)
            p.line([(x+26,782),(x+518,782)],'rule',3)


def draw_pair_note(p,d,v):
    a,b,c=list(d['fields'])
    pair(p,d,v,[a,b])
    if d.get('decoration')=='clocks':
        for i in range(2):
            cx,cy=(936,576+i*266) if p.portrait else (884+i*888,472)
            p.circle(cx,cy,21,'ground','structure',3)
            p.line([(cx,cy-13),(cx,cy),(cx+10,cy+6)],'structure',3)
    note(p,d,v,c)


def draw_passport(p,d,v):
    a,b,c,e=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,177,size=66)
        for i,key in enumerate([b,c]):
            y=753+i*146
            label(p,key,d['fields'][key]['label'],120,y,840,40)
            content(p,d,v,key,120,y+52,840,78,size=44)
        note(p,d,v,e,y=1080)
    else:
        panel(p,d,v,a,96,438,1728,160,size=70)
        for i,key in enumerate([b,c]):
            x=96+i*888
            label(p,key,d['fields'][key]['label'],x,622,840,40)
            content(p,d,v,key,x,674,840,58,size=43)
        note(p,d,v,e)


def draw_four(p,d,v):
    a,b,c,e=list(d['fields'])
    if p.portrait:
        label(p,a,d['fields'][a]['label'],96,542,888)
        content(p,d,v,a,96,598,888,90,size=58)
        for i,key in enumerate([b,c]):panel(p,d,v,key,96,724+i*171,888,149,size=43)
    else:
        label(p,a,d['fields'][a]['label'],96,438,1728)
        content(p,d,v,a,96,490,1728,62,size=58)
        for i,key in enumerate([b,c]):panel(p,d,v,key,96+i*888,580,840,150,size=44)
    note(p,d,v,e)


def draw_gap(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,205,size=57)
        p.line([(540,767),(540,796)],'axis',4,dash=True)
        panel(p,d,v,b,96,818,888,205,size=57)
    else:
        panel(p,d,v,a,96,438,748,270,size=58)
        panel(p,d,v,b,1076,438,748,270,size=58)
        p.line([(864,565),(918,565)],'axis',4,dash=True)
        p.line([(1002,565),(1056,565)],'axis',4,dash=True)
        p.text('furniture-question','?',928,526,64,80,size=68,kind='sans',weight=700,
               align='center',editable=False)
    note(p,d,v,c)


def draw_detour(p,d,v):
    a,b,c=list(d['fields'])
    panel(p,d,v,a,220 if p.portrait else 410,542 if p.portrait else 438,
          764 if p.portrait else 1414,205 if p.portrait else 180,size=59)
    if p.portrait:
        p.line([(174,568),(132,568),(132,812),(300,812)],'axis',4,arrow=True)
        label(p,b,d['fields'][b]['label'],332,792,652)
        content(p,d,v,b,332,858,652,170,size=57)
    else:
        p.line([(370,485),(200,485),(200,676),(404,676)],'axis',4,arrow=True)
        label(p,b,d['fields'][b]['label'],440,642,1384)
        content(p,d,v,b,440,695,1384,46,size=44)
    note(p,d,v,c)


def draw_target(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        p.rect(96,542,888,244,'ground','structure',sw=5)
        p.rect(108,554,864,220,'ground','rule',sw=2)
        label(p,a,d['fields'][a]['label'],132,574,816)
        content(p,d,v,a,132,640,816,112,size=63)
        for i,key in enumerate([b,c]):
            y=826+i*211
            label(p,key,d['fields'][key]['label'],96,y,888)
            content(p,d,v,key,96,y+58,888,126,size=49)
    else:
        p.rect(96,438,1728,180,'ground','structure',sw=5)
        p.rect(108,450,1704,156,'ground','rule',sw=2)
        label(p,a,d['fields'][a]['label'],132,464,1656)
        content(p,d,v,a,132,522,1656,70,size=66)
        for i,key in enumerate([b,c]):
            x=96+i*888
            label(p,key,d['fields'][key]['label'],x,652,840)
            content(p,d,v,key,x,712,840,154,size=52)


def draw_qa(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        for i,key in enumerate([a,b]):
            y=542+i*263
            p.line([(96,y+5),(96,y+222)],'structure',7)
            label(p,key,d['fields'][key]['label'],128,y,856)
            content(p,d,v,key,128,y+60,856,166,size=56)
    else:
        for i,key in enumerate([a,b]):
            x=96+i*888
            p.line([(x,448),(x,702)],'structure',7)
            label(p,key,d['fields'][key]['label'],x+32,438,808)
            content(p,d,v,key,x+32,506,808,200,size=57)
    note(p,d,v,c)


def draw_fork(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        pair(p,d,v,[a,b],top=562,height=227)
        p.line([(112,810),(968,810)],'axis',3,dash=True)
    else:
        pair(p,d,v,[a,b],top=500,height=214)
        p.line([(960,444),(960,470),(516,470),(516,494)],'axis',3)
        p.line([(960,470),(1404,470),(1404,494)],'axis',3,dash=True)
    note(p,d,v,c)


LAYOUTS={'fold':draw_fold,'ticket':draw_ticket,'stack':draw_stack,'roles':draw_roles,
         'pair_note':draw_pair_note,'passport':draw_passport,'four':draw_four,'gap':draw_gap,
         'detour':draw_detour,'target':draw_target,'qa':draw_qa,'fork':draw_fork}

def gate(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,216,size=59)
        panel(p,d,v,b,96,808,888,216,size=54,fill='ground')
        p.line([(508,774),(508,796)],'axis',4)
        p.line([(572,774),(572,796)],'axis',4)
    else:
        panel(p,d,v,a,96,438,748,270,size=60)
        panel(p,d,v,b,1076,438,748,270,size=59,fill='ground')
        for x in (944,976):p.line([(x,478),(x,668)],'axis',4)
        p.line([(864,570),(922,570)],'axis',4)
        p.line([(998,570),(1056,570)],'axis',4)
    note(p,d,v,c)


def files(p,d,v):
    a,b,c=list(d['fields'])
    for i,key in enumerate([a,b]):
        x,y,w,h=(96+i*48,552+i*268,840,214) if p.portrait else (96+i*936,462,792,246)
        p.rect(x+24,y-18,172,18,'band','structure',sw=2)
        panel(p,d,v,key,x,y,w,h,size=54 if p.portrait else 57)
    note(p,d,v,c)


def routes(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        for i,key in enumerate([a,b]):panel(p,d,v,key,96,542+i*278,760,216,size=54)
        p.line([(876,650),(940,650),(940,1080)],'axis',4,arrow=True)
        p.line([(876,928),(940,928)],'axis',4)
    else:
        for i,key in enumerate([a,b]):panel(p,d,v,key,96+i*980,438,748,270,size=58)
        p.line([(864,570),(960,728)],'axis',4,arrow=True)
        p.line([(1056,570),(960,728)],'axis',4)
    note(p,d,v,c)


def obligation(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,177,size=60)
        label(p,b,d['fields'][b]['label'],96,780,888)
        content(p,d,v,b,96,844,888,174,size=60)
        p.line([(96,1020),(96,1042),(984,1042),(984,1020)],'axis',4)
    else:
        panel(p,d,v,a,96,438,630,270,size=67)
        label(p,b,d['fields'][b]['label'],820,442,1004)
        content(p,d,v,b,820,506,1004,188,size=63)
        p.line([(746,580),(794,580)],'axis',4,arrow=True)
    note(p,d,v,c)


def conjunction(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,210,size=55)
        panel(p,d,v,b,96,834,888,210,size=55)
        x,y,w,h=430,772,220,48
    else:
        panel(p,d,v,a,96,438,748,270,size=58)
        panel(p,d,v,b,1076,438,748,270,size=58)
        x,y,w,h=878,540,164,70
    p.text('furniture-and','AND',x,y,w,h,size=48 if p.portrait else 52,kind='sans',
           weight=700,align='center',editable=False)
    note(p,d,v,c)


def callback(p,d,v):
    a,b,c=list(d['fields'])
    if p.portrait:
        panel(p,d,v,a,96,542,888,177,size=57)
        label(p,b,d['fields'][b]['label'],160,776,824)
        content(p,d,v,b,160,842,824,188,size=62)
        p.line([(128,1008),(112,1008),(112,784),(144,784)],'axis',4,arrow=True)
    else:
        panel(p,d,v,a,96,438,748,270,size=57)
        label(p,b,d['fields'][b]['label'],1100,438,724)
        content(p,d,v,b,1100,506,724,194,size=62)
        p.line([(864,648),(930,648),(930,470),(1056,470)],'axis',4,arrow=True)
    note(p,d,v,c)

LAYOUTS={**LAYOUTS,'gate':gate,'files':files,'routes':routes,
              'obligation':obligation,'and':conjunction,'callback':callback}
