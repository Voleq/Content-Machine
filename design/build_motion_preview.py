#!/usr/bin/env python3
"""Build portable, interactive motion reviews; never imported by the bot."""
from __future__ import annotations

import argparse
import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from design import build_all, contracts, longs

HERE = Path(__file__).resolve().parent


def attribute(value):
    return html.escape(str(value), quote=True)


def script_json(value):
    # A quote or a document excerpt must never terminate the data element.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('&', '\\u0026')


def shape(node, inks, extra=None):
    if node['tag'] not in ('rect', 'circle', 'path'):
        raise ValueError('Unsupported paint node in motion review')
    attrs = {**node['attrs'], **(extra or {})}
    for prop in ('fill', 'stroke'):
        if attrs.get(prop) in inks:
            attrs[prop] = inks[attrs[prop]]
    return '<' + node['tag'] + ' ' + ' '.join(f'{k}="{attribute(v)}"' for k, v in attrs.items()) + '/>'


def text_svg(name, slot, entry, values, boxes, colours, inks):
    role = entry['typeRoles'][slot['role']]
    box = boxes.get(name, [slot[k] for k in ('x', 'y', 'w', 'h')])
    minimum = (30 if entry['aspect'] == '9x16' else 24) if 'longRecipe' in entry else (34 if entry['aspect'] == '9x16' else 26)
    raw = {'name': name, 'box': box, 'example': values[name], 'font': role['font'],
           'size': role['size'], 'weight': role['weight'], 'minimum': minimum,
           'maxLines': slot.get('maxLinesByAspect', {}).get(entry['aspect'], slot.get('maxLines', role.get('maxLines', 1000)))}
    size, lines, top = build_all.fit(raw)
    x, y, w, h = box
    font = build_all.face(role['font'], size, role['weight'])
    if role.get('valign') == 'middle':
        bottom = max(font.getbbox(line or ' ', anchor='ls')[3] for line in lines)
        y += (h - ((len(lines) - 1) * size * 1.18 + bottom - top)) / 2
    anchor = {'left': 'start', 'right': 'end', 'center': 'middle'}[slot['align']]
    tx = x if anchor == 'start' else x + w if anchor == 'end' else x + w / 2
    ink = inks[colours.get(name, slot.get('colour', role['colour']))]
    fragments = []
    offset = 0
    for i, line in enumerate(lines):
        start = values[name].find(line, offset)
        if start < 0:
            start = offset
        fragments.append(f'<text x="{tx}" y="{y - top + 1 + i * size * 1.18}" '
                         f'font-family="{attribute(role["font"])}" font-size="{size}" font-weight="{role["weight"]}" '
                         f'text-anchor="{anchor}" fill="{attribute(ink)}" data-char-start="{start}">{html.escape(line)}</text>')
        offset = start + len(line)
    return ''.join(fragments)


def scene(entry, blank, inks):
    fill = contracts.example_fill(entry)
    groups = OrderedDict()
    values = deepcopy(entry['example'])
    boxes = {}
    colours = {}
    units = {}
    meta = {}
    if 'longRecipe' in entry:
        recipe = entry['longRecipe']
        p = longs.render(recipe['item'], recipe['aspect'], fill, inks, recipe.get('variant'))
        prepared = longs.prepare(entry, fill, inks)
        values = prepared['values']
        boxes = prepared['boxes']
        colours = prepared['colours']
        units = prepared['units']
        motion = prepared['motion']
        for node in p.nodes:
            if node.get('_scope') == 'body':
                groups.setdefault(node.get('_region', 'review-context'), []).append(node)
        if recipe['item']['model'] == 'clock':
            meta['clock'] = {'box': boxes['clock-area'], 'baseTime': values['clock-end']}
    else:
        motion = entry['motion']
        prepared = contracts.prepare(entry, fill, inks)
        values = prepared['values']
        boxes = prepared['boxes']
        if 'data-area' in entry['slots']:
            groups['data-area'] = prepared['nodes']
    markup = []
    for name, nodes in groups.items():
        parts = []
        for i, node in enumerate(nodes):
            extra = {'data-clock-hand': 'hour' if i == len(nodes) - 3 else 'minute'} if name == 'clock-area' and i in (len(nodes) - 3, len(nodes) - 2) else {}
            parts.append(shape(node, inks, extra))
        markup.append(f'<g data-slot="{attribute(name)}">' + ''.join(parts) + '</g>')
    for name, slot in entry['slots'].items():
        if not slot.get('region') and name in values:
            markup.append(f'<g data-slot="{attribute(name)}">' + text_svg(name, slot, entry, values, boxes, colours, inks) + '</g>')
    w, h = entry['canvas']
    img = base64.b64encode(blank).decode('ascii')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{attribute(entry["key"])}">'
           f'<image href="data:image/png;base64,{img}" x="0" y="0" width="{w}" height="{h}"/>'
           + ''.join(markup) + '</svg>')
    meta.update(key=entry['key'], canvas=[w, h], steps=motion['steps'], values=values, units=units,
                regions={n: {'children': s.get('children', []), 'uses': s.get('uses', [])} for n, s in entry['slots'].items() if s.get('region')},
                boxes={**{n: [s[k] for k in ('x', 'y', 'w', 'h')] for n, s in entry['slots'].items()}, **boxes},
                inks={k: inks[k] for k in ('ground', 'subject4', 'attention')})
    return svg, meta


def font_css():
    rules = []
    for filename, family, weight in [('ArchivoNarrow[wght].ttf', 'Archivo Narrow', '100 900'),
                                      ('CourierPrime-Regular.ttf', 'Courier Prime', '400'),
                                      ('CourierPrime-Bold.ttf', 'Courier Prime', '700')]:
        encoded = base64.b64encode((ROOT / 'assets/fonts' / filename).read_bytes()).decode('ascii')
        rules.append(f'@font-face{{font-family:"{family}";font-weight:{weight};src:url(data:font/ttf;base64,{encoded}) format("truetype");font-display:block}}')
    return ''.join(rules)


def build(delivery):
    delivery = Path(delivery).resolve()
    if any(delivery == p or p in delivery.parents for p in (ROOT / 'bot', ROOT / 'kit', ROOT / 'pipeline', ROOT / 'assets', HERE)):
        raise ValueError('Use an external build directory for generated motion reviews')
    inks = json.loads((ROOT / 'kit/design-tokens.json').read_text())['hours']['night']['plateInk']['paper']
    entries = []
    for manifest in sorted(delivery.glob('*/manifest.json')):
        for entry in json.loads(manifest.read_text()).get('plates', {}).values():
            if entry.get('motion'):
                entries.append((entry, manifest.parent / entry['files']['base']))
    if not entries:
        raise ValueError('Build a delivery with motion recipes first')
    groups = OrderedDict()
    for entry, file in sorted(entries, key=lambda row: (row[0].get('longRecipe', {}).get('item', {}).get('part', 2), row[0]['key'])):
        groups.setdefault(re.sub(r'-(16x9|9x16)$', '', entry['key']), []).append((entry, file))
    paginated = [list(groups.items())[i:i + 12] for i in range(0, len(groups), 12)]
    names = ['index.html'] + [f'gallery-{i + 1:02d}.html' for i in range(1, len(paginated))]
    output = delivery / 'motion'
    output.mkdir(exist_ok=True)
    css = font_css() + (HERE / 'motion_preview.css').read_text()
    js = (HERE / 'motion_preview.js').read_text()
    for page_groups, name in zip(paginated, names):
        parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
                 '<link rel="icon" href="data:,"><title>Dennis / animated plates</title><style>' + css + '</style>',
                 '<main><h1>Animated plate previews</h1><p>Illustrative examples. Play each plate, change the speed, or jump between ideas. Preview pacing is fixed; voice alignment stays with the bot.</p>',
                 '<nav aria-label="Pages">' + ''.join(f'<a href="{n}">Page {i + 1}</a>' for i, n in enumerate(names)) + '</nav>',
                 '<noscript>Enable JavaScript to play animations. The complete plates are visible below.</noscript>']
        for stem, layouts in page_groups:
            parts.append('<article><h2>' + html.escape(stem) + '</h2><div class="pair">')
            for entry, file in sorted(layouts, key=lambda row: row[0]['aspect']):
                svg, meta = scene(entry, file.read_bytes(), inks)
                parts += [f'<section class="player {"short" if entry["aspect"] == "9x16" else "long"}" data-key="{attribute(entry["key"])}">',
                          '<div class="screen">' + svg + '</div>',
                          '<div class="controls"><button data-command="play" aria-label="Play animation">Play</button>',
                          '<button data-command="restart" aria-label="Restart animation">Restart</button>',
                          '<button data-command="end" aria-label="Show final frame">End</button>',
                          '<label>Speed <select aria-label="Playback speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label></div>',
                          '<input class="timeline" type="range" min="0" max="1000" value="1000" aria-label="Animation position">',
                          '<div class="ideas" aria-label="Animation ideas"></div><p class="status" role="status" aria-live="off">Ready</p>',
                          '<script type="application/json" class="recipe">' + script_json(meta) + '</script></section>']
            parts.append('</div></article>')
        parts += ['</main><script>' + js + '</script></html>']
        (output / name).write_text(''.join(parts))
    source_files = [Path(__file__), HERE / 'motion_preview.js', HERE / 'motion_preview.css']
    (output / 'manifest.json').write_text(json.dumps({'layouts': len(entries), 'pages': names, 'integrated': False,
        'pacing': 'illustrative; no narration timing', 'moves': sorted(longs.MOVES),
        'sourceSha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}}, indent=2) + '\n')
    print(f'Built {len(entries)} animated layouts / {len(names)} portable pages into {output}; nothing installed in the bot.')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', required=True, type=Path)
    build(parser.parse_args().delivery)
