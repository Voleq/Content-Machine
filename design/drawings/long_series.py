"""Unwired long-video drawers. Plain series.paint nodes; no fonts or I/O."""
from __future__ import annotations
import math
from datetime import datetime,time
from ..core import node,points_path

def path(points,ink='structure',width=3,fill='none',close=False):
    return node('path',d=points_path(points,close),fill=fill,stroke=ink,**{'stroke-width':width})

def event_pins(box,positions,ink):
    """Dated events, already mapped to their real axis by the caller."""
    nodes=[]
    for x,y in positions:
        nodes.extend([path([(x,y),(x,y-48)],ink['attention'],3),
                      node('circle',cx=x,cy=y-65,r=21,fill=ink['ground'],stroke=ink['attention'],**{'stroke-width':3})])
    return nodes

def stage_ladder(box,rows,ink):
    """Four recorded stages per row; an untried settlement skips TRIED."""
    x,y,w,h=(box[k] for k in ('x','y','w','h'));nodes=[]
    for i,row in enumerate(rows):
        cy=y+(i+.5)*h/len(rows);xs=[x+j*w/3 for j in range(4)]
        nodes.append(path([(xs[0],cy),(xs[-1],cy)],ink['rule'],3))
        for j,cx in enumerate(xs):
            reached=j<row['stage'] and (j!=2 or row['tried'])
            nodes.append(node('circle',cx=cx,cy=cy,r=10,fill=ink['subject'] if reached else ink['ground'],stroke=ink['structure'],**{'stroke-width':2}))
    return nodes

def clock_face(box,value,ink):
    """Analog hands at an exact document time; no printed numerals."""
    t=time.fromisoformat('0'+value if value.index(':')==1 else value) if isinstance(value,str) else value
    if isinstance(t,datetime):t=t.time()
    if not isinstance(t,time):raise ValueError('clock_face needs an HH:MM[:SS] time')
    x,y,w,h=(box[k] for k in ('x','y','w','h'));cx=x+w/2;cy=y+h/2;r=min(w,h)/2-12
    nodes=[node('circle',cx=cx,cy=cy,r=r,fill=ink['ground'],stroke=ink['structure'],**{'stroke-width':4})]
    for k in range(60):
        a=k*math.pi/30-math.pi/2;inner=r-(19 if k%5==0 else 8)
        nodes.append(path([(cx+inner*math.cos(a),cy+inner*math.sin(a)),(cx+(r-3)*math.cos(a),cy+(r-3)*math.sin(a))],ink['structure'] if k%5==0 else ink['rule'],3 if k%5==0 else 2))
    for angle,length,width in (((t.hour%12+t.minute/60+t.second/3600)*math.pi/6,r*.52,9),((t.minute+t.second/60)*math.pi/30,r*.79,6)):
        angle-=math.pi/2;nodes.append(path([(cx,cy),(cx+length*math.cos(angle),cy+length*math.sin(angle))],ink['structure'],width))
    nodes.append(node('circle',cx=cx,cy=cy,r=8,fill=ink['attention']))
    return nodes

def trade_marks(box,trades,ink):
    """Triangles at actual price observations; triangle area scales by value."""
    largest=max((t['value'] for t in trades),default=0);nodes=[]
    for trade in trades:
        x,y=trade['point'];r=5+19*math.sqrt(trade['value']/largest) if largest else 5
        sign=-1 if trade['code']=='P' else 1
        points=[(x,y+sign*r),(x-r,y-sign*r),(x+r,y-sign*r)]
        tone='quiet' if trade['planned'] or trade['tax'] else 'subject5' if trade['code']=='P' else 'attention'
        nodes.append(path(points,ink['structure'],2,ink[tone],True))
    return nodes
