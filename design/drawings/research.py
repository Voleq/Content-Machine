"""Pure scene calculations; standard library only, no build or runtime I/O."""
from __future__ import annotations
import math
from . import chapters as story,charts
def ct(p,key,value,x,y,w,h=44,size=None,**kw):
    charts.text(p,key,value,x,y,w,h,size or (34 if p.portrait else 28),**kw)


def fixed(p,key,value,x,y,w,h=42):
    charts.label(p,key,value,x,y,w,h)


def draw_story(p,d,v):
    keys=list(d['fields'])
    layout=d['layout']
    if layout=='echo':
        for i,key in enumerate(keys[:3]):
            with p.stage(i+1):
                if p.portrait:story.panel(p,d,v,key,96,542+i*171,888,146,size=42)
                else:story.panel(p,d,v,key,96+i*592,444,544,268,size=48)
        with p.stage(4):story.note(p,d,v,keys[3])
        return
    if layout=='pair':
        for i,key in enumerate(keys[:2]):
            with p.stage(i+1):
                if p.portrait:story.panel(p,d,v,key,96,542+i*266,888,238,size=53)
                else:story.panel(p,d,v,key,96+i*888,438,840,270,size=57)
        with p.stage(3):story.note(p,d,v,keys[2])
    elif layout=='scope':
        with p.stage(1):story.panel(p,d,v,keys[0],96,542 if p.portrait else 438,p.w-192,220 if p.portrait else 180,size=62)
        with p.stage(2):
            y=812 if p.portrait else 652
            story.label(p,keys[1],d['fields'][keys[1]]['label'],96,y,p.w-192)
            story.content(p,d,v,keys[1],96,y+58,p.w-192,168 if p.portrait else 34,size=52 if p.portrait else 44)
        with p.stage(3):story.note(p,d,v,keys[2])
    else:
        for i,key in enumerate(keys):
            with p.stage(i+1):
                if p.portrait:story.panel(p,d,v,key,96,542+i*239,888,210,size=52)
                else:
                    y=438+i*144;p.line([(96,y),(1824,y)],'rule',2)
                    story.label(p,key,d['fields'][key]['label'],96,y+21,440,70)
                    story.content(p,d,v,key,600,y+18,1224,100,size=54)


def derive(d,v):
    model=d['model']
    if model=='unbilled':
        parts=[[v['contract_a'],v['billed_a']],[v['contract_b'],v['billed_b']]]
        require(all(sum(row)>0 for row in parts),'customer-asset totals must be positive')
        ratios=[row[0]/sum(row)*100 for row in parts]
        return {'parts':parts,'ratios':ratios,'delta_pp':ratios[1]-ratios[0]}
    if model=='ageing':
        parts=[[v['current_a'],v['late_a'],v['old_a']],[v['current_b'],v['late_b'],v['old_b']]]
        require(all(sum(row)>0 for row in parts),'ageing totals must be positive')
        ratios=[row[2]/sum(row)*100 for row in parts]
        return {'parts':parts,'ratios':ratios,'delta_pp':ratios[1]-ratios[0]}
    if model=='fees':
        parts=[[v['audit_a'],v['other_a']],[v['audit_b'],v['other_b']]]
        require(all(sum(row)>0 for row in parts),'fee totals must be positive')
        ratios=[row[1]/sum(row)*100 for row in parts]
        return {'parts':parts,'ratios':ratios,'delta_pp':ratios[1]-ratios[0]}
    if model=='supplier_finance':
        require(v['finance_a']<=v['payables_a'] and v['finance_b']<=v['payables_b'],'supplier finance must be a subset of the stated payables')
        parts=[[v['finance_a'],v['payables_a']-v['finance_a']],[v['finance_b'],v['payables_b']-v['finance_b']]]
        ratios=[row[0]/sum(row)*100 for row in parts]
        return {'parts':parts,'ratios':ratios,'delta_pp':ratios[1]-ratios[0]}
    if model=='asset_bridge':
        end=v['opening']+v['additions']-v['amortisation']-v['impairment']
        require(end>=0 and math.isclose(end,v['closing'],abs_tol=.001,rel_tol=1e-9),'asset roll-forward does not reconcile; do not omit other movements')
        return {'closing':end,'movements':[v['opening'],v['additions'],-v['amortisation'],-v['impairment'],end]}
    if model=='repeated_exclusion':
        values=[v['charge_a'],v['charge_b'],v['charge_c']]
        return {'charges':values,'periods_with_charge':sum(n>0 for n in values),'total':sum(values)}
    if model=='goodwill':
        ratios=[v['goodwill_a']/v['equity_a']*100,v['goodwill_b']/v['equity_b']*100]
        return {'ratios':ratios,'equity_less_goodwill':[v['equity_a']-v['goodwill_a'],v['equity_b']-v['goodwill_b']]}
    if model=='correction':
        before=[v['revenue_before'],v['profit_before'],v['equity_before']]
        after=[v['revenue_after'],v['profit_after'],v['equity_after']]
        return {'before':before,'after':after,'changes':[b-a for a,b in zip(before,after)]}
    raise ValueError('unknown chart model')


def require(ok,message):
    if not ok:raise ValueError(message)


def summary_text(p,value,*,composition=False):
    with p.stage(3):charts.caption(p,value,y=1200 if p.portrait and composition else None)


def draw_composition(p,d,v,a):
    model=d['model'];parts=a['parts']
    legends={
      'unbilled':[('CONTRACT ASSETS','subject'),('BILLED RECEIVABLES','subject2')],
      'ageing':[('CURRENT','subject'),('1–90D LATE','subject2'),('>90D LATE','subject3')],
      'fees':[('AUDIT','subject'),('NON-AUDIT','subject2')],
      'supplier_finance':[('SUPPLIER FINANCE','subject'),('OTHER PAYABLES','subject2')],
    }[model]
    charts.unit(p,'100% = PERIOD TOTAL / AMOUNTS IN $m')
    charts.legend(p,legends)
    for i,row in enumerate(parts):
        key='period_a' if i==0 else 'period_b'
        x,y,w,h=(96,742+i*268,888,65) if p.portrait else (500,550+i*153,1000,48)
        ct(p,key,v[key],96,672+i*268 if p.portrait else y-8,500 if p.portrait else 360,42,40,bold=True)
        p.rect(x,y,w,h,'band','rule',sw=2)
        with p.stage(i+1):
            cursor=x
            if p.filled:
                for j,value in enumerate(row):
                    width=w*value/sum(row)
                    p.rect(cursor,y,width,h,charts.COLOURS[j],'structure' if p.ground=='paper' else None,sw=2)
                    cursor+=width
            ct(p,f'ratio-{i}',charts.fmt(a['ratios'][i],'%'),650 if p.portrait else 1540,
               662+i*268 if p.portrait else y-12,334 if p.portrait else 284,64,54,mono=True,bold=True,align='right')
            values=' / '.join(charts.fmt(n,'$m') for n in row)
            ct(p,f'amounts-{i}','In legend order: '+values,96 if p.portrait else 500,
               825+i*268 if p.portrait else y+68,888 if p.portrait else 1324,80 if p.portrait else 44,
               34 if p.portrait else 28,mono=True)
    name={'unbilled':'Unbilled share','ageing':'Over-90-day share','fees':'Non-audit fee share','supplier_finance':'Supplier-finance share'}[model]
    summary_text(p,name+' changed '+charts.fmt(a['delta_pp'],'pp',signed=True)+'.',composition=True)


def draw_columns(p,d,v,a):
    model=d['model'];charts.unit(p,'SAME REPORTING BASIS / $m')
    if model=='repeated_exclusion':
        values=a['charges'];high=max(1,math.ceil(max(values)*1.2/10)*10)
        # Leave enough room for every permitted twelve-character period label.
        box=(208,668,776,378) if p.portrait else None
        plot=charts.Plot(p,'exclusion',(-.5,2.5),(0,high),box=box)
        plot.axes(yticks=[0,high/2,high])
        for i,value in enumerate(values):
            with p.stage(i+1):
                plot.bar(i,value)
                px,py=plot.xy(i,value)
                ct(p,f'charge-{i}',charts.n(value),px-84,py-56,168,42,40,mono=True,bold=True,align='center')
            px,_=plot.xy(i,0);key=['period_a','period_b','period_c'][i]
            width=252 if p.portrait else 260
            ct(p,key,v[key],px-width/2,1068 if p.portrait else 782,width,42,34 if p.portrait else 28,mono=True,align='center')
        summary_text(p,f'The same exclusion appears in {a["periods_with_charge"]} of 3 supplied periods.')
    elif model=='goodwill':
        values=[v[k] for k in ('goodwill_a','equity_a','goodwill_b','equity_b')]
        high=max(1,math.ceil(max(values)*1.2/100)*100)
        charts.legend(p,[('GOODWILL','subject'),('BOOK EQUITY','subject2')])
        plot=charts.Plot(p,'goodwill',(-.5,1.5),(0,high));plot.axes(yticks=[0,high/2,high])
        for i in range(2):
            with p.stage(i+1):
                plot.bar(i-.18,values[i*2],width=.30)
                plot.bar(i+.18,values[i*2+1],width=.30,colour='subject2')
            px,_=plot.xy(i,0);key=['period_a','period_b'][i]
            ct(p,key,v[key],px-130,1068 if p.portrait else 782,260,42,34 if p.portrait else 28,mono=True,align='center')
        with p.stage(3):
            charts.summary(p,[('GOODWILL / EQUITY A',charts.fmt(a['ratios'][0],'%')),
                              ('GOODWILL / EQUITY B',charts.fmt(a['ratios'][1],'%'))])
    else:
        values=a['movements'];levels=[v['opening'],v['opening']+v['additions'],v['opening']+v['additions']-v['amortisation'],a['closing'],a['closing']]
        high=max(1,math.ceil(max(levels)*1.2/50)*50)
        plot=charts.Plot(p,'asset-bridge',(-.5,4.5),(0,high))
        plot.axes(xticks=list(enumerate(['OPEN','ADDED','AMORT','LOSS','CLOSE'])),yticks=[0,high/2,high])
        current=0
        for i,value in enumerate(values):
            with p.stage([1,2,3,3,4][i]):
                if i in (0,4):plot.bar(i,value,colour='subject' if i==0 else 'subject2')
                else:plot.bar(i,current+value,base_value=current,colour='subject' if value>=0 else 'down')
                current=value if i in (0,4) else current+value
        summary_text(p,'Closing carrying value: '+charts.fmt(a['closing'],'$m')+'.')


def draw_correction(p,d,v,a):
    charts.unit(p,'CORRECTION / SAME PERIOD / $m')
    bound=max(1,math.ceil(max(abs(n) for n in a['changes'])/10)*10)
    left,right=(380,900) if p.portrait else (650,1580);middle=(left+right)/2
    top=700 if p.portrait else 547;step=150 if p.portrait else 100
    p.line([(middle,top-30),(middle,top+step*2+50)],'axis',3)
    for i,(name,value) in enumerate(zip(['REVENUE','NET PROFIT','BOOK EQUITY'],a['changes'])):
        y=top+i*step;fixed(p,f'line-{i}',name,96,y-6,left-120,44)
        with p.stage(i+1):
            end=middle+value/bound*(right-left)/2
            if p.filled:p.rect(min(middle,end),y,abs(end-middle),32,'down' if value<0 else 'subject')
            ct(p,f'change-{i}',charts.fmt(value,'$m',signed=True),96 if p.portrait else 1600,
               y+54 if p.portrait else y-5,left-120 if p.portrait else 224,46,36,mono=True,bold=True)
    for i,value in enumerate([-bound,0,bound]):
        fixed(p,f'tick-{i}',charts.n(value),left+(right-left)*i/2-60,1185 if p.portrait else 845,120,38)
