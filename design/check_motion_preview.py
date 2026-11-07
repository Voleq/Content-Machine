#!/usr/bin/env python3
"""Browser regression checks for a generated motion review, never bot code."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread


def check(delivery, chromium=None):
    from playwright.sync_api import sync_playwright

    folder = Path(delivery).resolve() / 'motion'
    manifest = json.loads((folder / 'manifest.json').read_text())

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(folder)))
    Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium, headless=True,
                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            errors = []
            requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append((request.url, request.resource_type)))
            layouts = 0
            seen_moves = set()
            for filename in manifest['pages']:
                page.goto(base + filename, wait_until='load')
                page.wait_for_function('document.documentElement.dataset.motionReady === "true"')
                results = page.locator('.player').evaluate_all('''roots => roots.map(root => {
                  const p = root.motionPlayer, failures = [], moves = new Set(p.recipe.steps.map(s => s.move || s.action));
                  const demand = (condition, message) => {if (!condition) failures.push(message);};
                  demand(!p.playing, 'No autoplay');
                  p.render(0);
                  demand([...p.groups.values()].every(g => g.style.opacity === '0'), 'Replay starts before the first reveal');
                  p.render(150);
                  demand([...p.groups.values()].some(g => Number(g.style.opacity) > 0 && Number(g.style.opacity) < 1), 'Appear has an intermediate opacity');
                  for (const e of p.effects) {
                    moves.add(e.move);
                    p.render(e.start + e.duration / 2);
                    if (e.move === 'line-draw') for (const {path, length} of e.paths) {
                      const offset = Number(path.getAttribute('stroke-dashoffset'));
                      demand(offset > 0 && offset < length, 'Line has an intermediate stroke length');
                    }
                    if (e.move === 'bars-grow') for (const {rect, width} of e.bars) {
                      const current = Number(rect.getAttribute('width'));
                      demand(!width || current > 0 && current < width, 'Bars grow within their true width');
                    }
                    if (e.move === 'count-up') for (const n of e.numbers) {
                      if (n.name === e.spec.slot && Math.abs(n.spec.value - n.from) >= 2) demand(n.text.textContent !== n.spec.text, 'Count-up shows an intermediate figure');
                    }
                    if (e.clip) demand(Number(e.clip.rect.getAttribute('width')) > 0 && Number(e.clip.rect.getAttribute('width')) < e.clip.width, 'Clip reveals an intermediate area');
                    if (e.marks) for (const mark of e.marks) demand(Number(mark.rect.getAttribute('width')) > 0 && Number(mark.rect.getAttribute('width')) < mark.width, 'Highlight has an intermediate width');
                    if (e.move === 'pen-circle') demand(Number(e.mark.getAttribute('stroke-dashoffset')) > 0 && Number(e.mark.getAttribute('stroke-dashoffset')) < e.length, 'Circle draws over time');
                    if (e.move === 'zoom-to-slot') demand(p.svg.getAttribute('viewBox') !== '0 0 ' + p.recipe.canvas.join(' '), 'View zooms into the target');
                    if (e.move === 'clock-run') {
                      demand(e.hands.length === 2 && e.hands.every(h => h.getAttribute('transform')), 'Both hands move');
                      demand(p.groups.get(e.spec.toValueSlot).style.opacity === '0', 'Checkpoint total stays hidden until arrival');
                      p.time = e.start + e.duration / 2; p.pause();
                      demand(p.time === e.start + e.duration, 'Pause lands exactly on the documented endpoint');
                      demand(e.counter.text.textContent === e.to.text, 'Paused total is the documented number');
                    }
                  }
                  p.render(p.duration);
                  for (const e of p.effects) {
                    if (e.numbers) for (const n of e.numbers) demand(n.text.textContent === n.spec.text, 'Count-up ends on the exact supplied figure');
                    if (e.move === 'clock-run') demand(p.groups.get(e.spec.toValueSlot).style.opacity === '1', 'Reached checkpoint is visible');
                  }
                  // Replay changes geometry again and returns to the same endpoint.
                  const final = p.svg.outerHTML;
                  p.render(0); p.render(p.duration);
                  demand(p.svg.outerHTML === final, 'Replay is deterministic');
                  return {key: p.recipe.key, moves: [...moves], failures};
                })''')
                for result in results:
                    assert not result['failures'], result
                    seen_moves.update(result['moves'])
                layouts += len(results)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), filename
                page.set_viewport_size({'width': 1440, 'height': 1000})
            assert layouts == manifest['layouts']
            assert not errors, errors
            assert not [(url, kind) for url, kind in requests if url.startswith('http') and kind != 'document']

            page.goto(base + 'index.html', wait_until='load')
            page.wait_for_function('document.documentElement.dataset.motionReady === "true"')
            first = page.locator('.player').first
            first.locator('[data-command="play"]').click()
            page.wait_for_function('document.querySelector(".player").motionPlayer.time > 350')
            first.locator('[data-command="play"]').click()
            assert first.get_attribute('data-playing') == 'false'
            first.locator('[data-command="restart"]').click()
            assert first.get_attribute('data-playing') == 'true'
            first.locator('[data-command="end"]').click()
            assert first.locator('.timeline').input_value() == '1000'
            first.locator('.timeline').press('Home')
            assert first.get_attribute('data-playing') == 'false'
            first.locator('[data-command="end"]').click()
            if len(manifest['pages']) > 1:
                page.locator('nav a').nth(1).click()
                assert page.url.endswith(manifest['pages'][1])

            # A copied single HTML page keeps its fonts, shapes and player offline.
            page.goto('about:blank')
            context.set_offline(True)
            page.set_content((folder / 'index.html').read_text(), wait_until='load')
            page.wait_for_function('document.documentElement.dataset.motionReady === "true"')
            first = page.locator('.player').first
            first.locator('[data-command="play"]').click()
            page.wait_for_function('document.querySelector(".player").motionPlayer.time > 200')
            first.locator('[data-command="end"]').click()
            assert not errors, errors
            browser.close()
        print(f'PASS: {layouts} animated layouts, {len(manifest["pages"])} portable pages, desktop/mobile and offline playback; intermediate geometry, exact totals, checkpoint pauses, replay and controls.')
        print('Verified moves: ' + ', '.join(sorted(seen_moves)))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', required=True, type=Path)
    parser.add_argument('--chromium')
    options = parser.parse_args()
    check(options.delivery, options.chromium)
