/* Standalone review player. Fixed preview pacing, no bot or network dependency. */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const clamp = n => Math.max(0, Math.min(1, n));
  const ease = n => { n = clamp(n); return n * n * (3 - 2 * n); };
  const svgNode = (tag, attrs = {}) => {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  };
  const parseNumber = text => {
    const match = /^([−-]?)(\$?)(\d[\d,]*(?:\.\d+)?)(m|bn|%|x)?$/.exec(text);
    if (!match) return null;
    return {value: Number((match[1] ? '-' : '') + match[3].replaceAll(',', '')),
      prefix: match[2], suffix: match[4] || '', places: (match[3].split('.')[1] || '').length, text};
  };
  const formatNumber = (spec, value, p) => p >= 1 ? spec.text :
    (value < 0 && Math.abs(value) >= 0.5 * 10 ** -spec.places ? '-' : '') + spec.prefix +
    Math.abs(value).toLocaleString('en-US', {minimumFractionDigits: spec.places, maximumFractionDigits: spec.places}) + spec.suffix;
  const clockSeconds = text => text.split(':').reduce((sum, n, i) => sum + Number(n) * [3600, 60, 1][i], 0);
  let nextId = 0;

  class Player {
    constructor(root) {
      this.root = root;
      this.recipe = JSON.parse(root.querySelector('.recipe').textContent);
      this.svg = root.querySelector('svg');
      this.groups = new Map([...this.svg.querySelectorAll('[data-slot]')].map(g => [g.dataset.slot, g]));
      this.playButton = root.querySelector('[data-command="play"]');
      this.slider = root.querySelector('.timeline');
      this.status = root.querySelector('.status');
      this.speed = root.querySelector('select');
      this.defs = svgNode('defs');
      this.svg.prepend(this.defs);
      this.effects = [];
      this.clockRuns = [];
      this.first = new Map();
      this.stages = [];
      let start = 0;
      for (let i = 0; i < this.recipe.steps.length; i++) {
        const step = this.recipe.steps[i];
        const primary = step.move || step.action;
        const effectLength = (step.effects || []).length * 620;
        const duration = primary === 'clock-run' ? 4600 : Math.max(1650, 700 + effectLength);
        const stage = {step, start, duration, index: i};
        this.stages.push(stage);
        const members = [step.slot, ...(step.includeSlots || [])].flatMap(n => this.members(n));
        for (const name of members) if (!this.first.has(name)) this.first.set(name, stage);
        if (primary === 'clock-run') this.clockRuns.push(stage);
        this.addEffect(primary, step, stage, start, primary === 'clock-run' ? duration : 750);
        (step.effects || []).forEach((effect, j) => this.addEffect(effect.move, effect, stage, start + 650 + j * 620, 620));
        start += duration + 450;
      }
      this.duration = start;
      this.time = start;
      this.playing = false;
      this.frame = null;
      root.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => {
        if (button.dataset.command === 'play') this.playing ? this.pause() : this.play();
        if (button.dataset.command === 'restart') { this.stop(); this.time = 0; this.render(0); this.play(); }
        if (button.dataset.command === 'end') { this.stop(); this.time = this.duration; this.render(this.time); }
      }));
      this.slider.addEventListener('input', () => {
        this.stop();
        this.time = this.snapCheckpoint(Number(this.slider.value) / 1000 * this.duration);
        this.render(this.time);
      });
      const ideas = root.querySelector('.ideas');
      this.stages.forEach(stage => {
        const button = document.createElement('button');
        button.textContent = String(stage.index + 1);
        button.setAttribute('aria-label', 'Play idea ' + (stage.index + 1));
        button.addEventListener('click', () => { this.stop(); this.time = stage.start; this.render(this.time); this.play(); });
        ideas.append(button);
      });
      root.motionPlayer = this;
      this.render(this.duration);
    }

    members(name) {
      const result = [name];
      for (const child of this.recipe.regions[name]?.children || []) result.push(...this.members(child));
      return result;
    }

    addEffect(move, spec, stage, start, duration) {
      if (!move || move === 'appear') return;
      const target = this.groups.get(spec.slot);
      if (!target) return;
      const effect = {move, spec, stage, start, duration, target};
      if (move === 'clip-in') {
        effect.clip = this.makeClip(target.getBBox());
      } else if (move === 'line-draw') {
        effect.paths = [...target.querySelectorAll('path')].filter(p => p.getAttribute('fill') === 'none').map(path => ({path, length: path.getTotalLength(), dash: path.getAttribute('stroke-dasharray')}));
      } else if (move === 'bars-grow') {
        effect.bars = [...target.querySelectorAll('rect')].map(rect => ({rect, width: Number(rect.getAttribute('width'))}));
      } else if (move === 'count-up') {
        effect.numbers = [spec.slot, ...(spec.includeSlots || [])].map(n => this.numeric(n)).filter(Boolean);
        // A running total starts from the preceding row, rather than zero.
        for (const n of effect.numbers) {
          const row = /^total-(\d+)$/.exec(n.name);
          if (row && Number(row[1]) > 1 && this.recipe.values.tag) n.from = parseNumber(this.recipe.values['total-' + (Number(row[1]) - 1)])?.value || 0;
        }
      } else if (move === 'highlight') {
        const texts = [...target.querySelectorAll('text')];
        if (texts.length) {
          effect.marks = this.highlights(target, texts, spec.textRange);
        } else {
          effect.clip = this.makeClip(target.getBBox());
        }
      } else if (move === 'pen-circle') {
        const box = target.getBBox();
        effect.mark = svgNode('ellipse', {cx: box.x + box.width / 2, cy: box.y + box.height / 2,
          rx: box.width / 2 + 13, ry: box.height / 2 + 12, fill: 'none', stroke: this.recipe.inks.attention, 'stroke-width': 5});
        target.append(effect.mark);
        effect.length = effect.mark.getTotalLength();
      } else if (move === 'zoom-to-slot') {
        const b = target.getBBox(), [w, h] = this.recipe.canvas, ratio = w / h;
        let zw = Math.max(b.width + 150, (b.height + 150) * ratio), zh = zw / ratio;
        zw = Math.min(zw, w); zh = Math.min(zh, h);
        effect.zoom = [Math.max(0, Math.min(w - zw, b.x + b.width / 2 - zw / 2)), Math.max(0, Math.min(h - zh, b.y + b.height / 2 - zh / 2)), zw, zh];
      } else if (move === 'clock-run') {
        effect.counter = this.numeric(spec.totalSlot);
        effect.fromTime = clockSeconds(this.recipe.values[spec.fromTimeSlot]);
        effect.toTime = clockSeconds(this.recipe.values[spec.toTimeSlot]);
        effect.to = parseNumber(this.recipe.values[spec.toValueSlot]);
        effect.from = spec.fromValueSlot ? parseNumber(this.recipe.values[spec.fromValueSlot]).value : spec.initialValue;
        effect.hands = [...target.querySelectorAll('[data-clock-hand]')];
      }
      this.effects.push(effect);
    }

    numeric(name) {
      const target = this.groups.get(name), spec = parseNumber(this.recipe.values[name] || '');
      const texts = target ? [...target.querySelectorAll('text')] : [];
      return spec && texts.length === 1 ? {name, spec, text: texts[0], from: 0} : null;
    }

    makeClip(box) {
      const id = 'motion-clip-' + (++nextId);
      const path = svgNode('clipPath', {id, clipPathUnits: 'userSpaceOnUse'});
      const rect = svgNode('rect', {x: box.x - 4, y: box.y - 4, width: box.width + 8, height: box.height + 8});
      path.append(rect); this.defs.append(path);
      return {id, rect, width: box.width + 8};
    }

    highlights(target, texts, range) {
      const marks = [];
      for (const text of texts) {
        let box;
        if (range) {
          const offset = Number(text.dataset.charStart), start = Math.max(0, range.start - offset), end = Math.min(text.textContent.length, range.end - offset);
          if (start >= end) continue;
          const a = text.getExtentOfChar(start), b = text.getExtentOfChar(end - 1);
          box = {x: a.x, y: Math.min(a.y, b.y), width: b.x + b.width - a.x, height: Math.max(a.height, b.height)};
        } else box = text.getBBox();
        const rect = svgNode('rect', {x: box.x - 5, y: box.y - 2, width: box.width + 10, height: box.height + 4, fill: this.recipe.inks.subject4});
        target.insertBefore(rect, target.firstChild);
        marks.push({rect, width: box.width + 10});
      }
      return marks;
    }

    render(time) {
      const current = [...this.stages].reverse().find(s => time >= s.start) || this.stages[0];
      for (const [name, group] of this.groups) {
        const first = this.first.get(name) || this.stages[0];
        group.style.opacity = String(ease((time - first.start) / 320));
        group.removeAttribute('clip-path');
      }
      this.svg.setAttribute('viewBox', '0 0 ' + this.recipe.canvas.join(' '));
      for (const e of this.effects) {
        const raw = clamp((time - e.start) / e.duration), p = e.move === 'clock-run' ? raw : ease(raw);
        if (e.move === 'clip-in' || e.move === 'highlight' && e.clip) {
          e.target.setAttribute('clip-path', 'url(#' + e.clip.id + ')'); e.clip.rect.setAttribute('width', e.clip.width * p);
        } else if (e.move === 'line-draw') {
          for (const {path, length, dash} of e.paths) {
            if (p < 1) { path.setAttribute('stroke-dasharray', length); path.setAttribute('stroke-dashoffset', length * (1 - p)); }
            else { path.removeAttribute('stroke-dashoffset'); dash === null ? path.removeAttribute('stroke-dasharray') : path.setAttribute('stroke-dasharray', dash); }
          }
        } else if (e.move === 'bars-grow') {
          for (const {rect, width} of e.bars) rect.setAttribute('width', width * p);
        } else if (e.move === 'count-up') {
          for (const n of e.numbers) n.text.textContent = formatNumber(n.spec, n.from + (n.spec.value - n.from) * p, p);
        } else if (e.move === 'highlight' && e.marks) {
          for (const {rect, width} of e.marks) rect.setAttribute('width', width * p);
        } else if (e.move === 'pen-circle') {
          e.mark.style.opacity = time >= e.start ? '1' : '0';
          e.mark.setAttribute('stroke-dasharray', e.length); e.mark.setAttribute('stroke-dashoffset', e.length * (1 - p));
        } else if (e.move === 'zoom-to-slot' && time >= e.start) {
          const full = [0, 0, ...this.recipe.canvas];
          this.svg.setAttribute('viewBox', full.map((n, i) => n + (e.zoom[i] - n) * p).join(' '));
        } else if (e.move === 'clock-run') {
          if (time < e.start) continue;
          const seconds = e.fromTime + (e.toTime - e.fromTime) * p;
          const base = clockSeconds(this.recipe.clock.baseTime), b = this.recipe.clock.box;
          for (const hand of e.hands) hand.setAttribute('transform', `rotate(${(seconds - base) * (hand.dataset.clockHand === 'hour' ? 1 / 120 : 1 / 10)}, ${b[0] + b[2] / 2}, ${b[1] + b[3] / 2})`);
          if (e.counter) e.counter.text.textContent = formatNumber(e.to, e.from + (e.to.value - e.from) * p, p);
          for (const name of [e.spec.toTimeSlot, e.spec.toValueSlot]) {
            const group = this.groups.get(name); if (group) group.style.opacity = p >= 1 ? '1' : '0';
          }
        }
      }
      this.slider.value = String(Math.round(time / this.duration * 1000));
      const cue = this.recipe.values[current.step.cueSlot] || '';
      this.status.textContent = 'Idea ' + (current.index + 1) + ' / ' + this.stages.length + (cue ? ' · ' + cue : '');
      this.root.querySelectorAll('.ideas button').forEach((b, i) => b.setAttribute('aria-pressed', String(i === current.index)));
      this.root.dataset.position = String(Math.round(time));
      this.root.dataset.playing = String(this.playing);
    }

    snapCheckpoint(time) {
      const run = this.clockRuns.find(r => time >= r.start && time < r.start + r.duration);
      return run ? run.start + run.duration : time;
    }

    play() {
      if (this.time >= this.duration) this.time = 0;
      this.playing = true; this.playButton.textContent = 'Pause';
      this.playButton.setAttribute('aria-label', 'Pause animation');
      this.render(this.time);
      let previous = performance.now();
      const tick = now => {
        if (!this.playing) return;
        this.time = Math.min(this.duration, this.time + (now - previous) * Number(this.speed.value));
        previous = now; this.render(this.time);
        if (this.time >= this.duration) { this.stop(); this.render(this.time); }
        else this.frame = requestAnimationFrame(tick);
      };
      this.frame = requestAnimationFrame(tick);
    }

    pause() {
      this.stop(); this.time = this.snapCheckpoint(this.time); this.render(this.time);
    }

    stop() {
      this.playing = false; cancelAnimationFrame(this.frame); this.frame = null;
      this.playButton.textContent = 'Play'; this.playButton.setAttribute('aria-label', 'Play animation');
      this.root.dataset.playing = 'false';
    }
  }

  document.fonts.ready.then(() => {
    for (const root of document.querySelectorAll('.player')) new Player(root);
    // Pause at a real checkpoint when the browser tab loses visibility.
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) document.querySelectorAll('.player').forEach(root => { if (root.motionPlayer.playing) root.motionPlayer.pause(); });
    });
    document.documentElement.dataset.motionReady = 'true';
  });
})();
