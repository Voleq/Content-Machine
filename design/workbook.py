"""Build-time validation against the actual bot workbook's named sheets."""
from __future__ import annotations
import re
from openpyxl import load_workbook

def schema(path):
    book=load_workbook(path,read_only=True,data_only=False);result={}
    try:
        for name in ('History','Quarters','Snapshot'):
            rows=iter(book[name].iter_rows(values_only=True))
            for row in rows:
                if 'field_key' in row:header=row;break
            else:raise ValueError('Workbook sheet has no field_key header: '+name)
            key_column=header.index('field_key');keys=set()
            for row in rows:
                key=row[key_column] if len(row)>key_column else None
                if isinstance(key,str) and re.fullmatch(r'[a-z][a-z0-9_]*',key):keys.add(key)
            periods={v for v in header if isinstance(v,str) and re.fullmatch(r'FY-[0-4]|LTM|Q-[0-7]',v)}
            result[name]={'fields':keys,'periods':periods}
    finally:book.close()
    return result

def validate_source(source,tables):
    if source['kind']=='filing':
        if not source.get('location') or not source.get('period'):raise ValueError('Missing filing location/period')
        return
    if source['kind']!='workbook':raise ValueError('Unknown figure source')
    table=tables.get(source['sheet'])
    if table is None or source['field'] not in table['fields']:raise ValueError('Unknown workbook row: '+source['sheet']+'!'+source['field'])
    for period in re.findall(r'FY-\d+|Q-\d+|LTM',source['period']):
        if source['sheet']!='Snapshot' and period not in table['periods']:raise ValueError('Unsupported workbook period '+period)
    if not source.get('period'):raise ValueError('Workbook reference needs its reporting period')
