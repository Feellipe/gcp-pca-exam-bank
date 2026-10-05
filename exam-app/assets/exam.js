/* PCA practice-exam — application logic (component).
   Inlined into the exported single-file app by scripts/export_exam_app.py.
   Everything is client-side and offline; the only network use is a youtu.be
   link the user chooses to tap. */
'use strict';

var DATA = JSON.parse(document.getElementById('exam-data').textContent);
var BY_LABEL = {};
DATA.questions.forEach(function (q) { BY_LABEL[q.l] = q; });
var SEC_PER_Q = DATA.per_question_seconds;
var SAVE_KEY = 'pca-exam-v1';

/* Session state. Persisted to localStorage (best effort) so a phone browser
   reload, or the app being backgrounded on a commute, does not lose the run. */
var S = null;
var tick = null;

/* --------------------------------------------------------------- persistence */
function save() {
  try { localStorage.setItem(SAVE_KEY, JSON.stringify(S)); } catch (e) { /* sandboxed */ }
}
function loadSaved() {
  try { return JSON.parse(localStorage.getItem(SAVE_KEY) || 'null'); } catch (e) { return null; }
}
function clearSaved() {
  try { localStorage.removeItem(SAVE_KEY); } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------- helpers */
function shuffle(a) {
  for (var i = a.length - 1; i > 0; i--) {
    var j = Math.floor(Math.random() * (i + 1));
    var t = a[i]; a[i] = a[j]; a[j] = t;
  }
  return a;
}
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function correctLetters(q) {
  return q.correct.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
}
function isRight(q, chosen) {
  var a = chosen.slice().sort().join(',');
  var b = correctLetters(q).slice().sort().join(',');
  return a === b && a !== '';
}
function mmss(s) {
  s = Math.max(0, s | 0);
  var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  var p = function (n) { return n < 10 ? '0' + n : '' + n; };
  return (h ? h + ':' + p(m) : '' + m) + ':' + p(x);
}
function poolFor(cats) {
  if (!cats.length) return DATA.questions.slice();
  var set = {};
  cats.forEach(function (c) { set[c] = 1; });
  return DATA.questions.filter(function (q) {
    return q.concepts.some(function (c) { return set[c.cat]; });
  });
}
function optionText(q, letter) {
  for (var i = 0; i < q.o.length; i++) if (q.o[i].l === letter) return q.o[i].t;
  return '';
}
/* Selection rules for one option, split out of the click handler so they can be
   tested directly. Single-answer questions replace; multi-answer questions cap
   at the required count and drop the oldest pick, so a mis-tap is recoverable. */
function pickOption(it, q, L) {
  var max = correctLetters(q).length;
  var at = it.chosen.indexOf(L);
  if (at >= 0) { it.chosen.splice(at, 1); return; }
  if (max === 1) { it.chosen = [L]; return; }
  if (it.chosen.length >= max) it.chosen.shift();
  it.chosen.push(L);
}
/* Repaint just the option buttons after a tap. A full re-render would rebuild the
   stem too and can shift the scroll position mid-question on a phone. */
function paintOptions() {
  var it = S.items[S.idx];
  Array.prototype.forEach.call(document.querySelectorAll('.opt'), function (n) {
    n.setAttribute('aria-pressed', it.chosen.indexOf(n.dataset.letter) >= 0);
  });
}
function scrollFeedback() {
  var fb = document.querySelector('.fb');
  if (fb && fb.scrollIntoView) fb.scrollIntoView({ block: 'start' });
}

/* -------------------------------------------------------------------- session */
function newItem(label) {
  return { label: label, chosen: [], checked: false, revealed: false, ok: null };
}
function startExam(cats, wantN) {
  var pool = shuffle(poolFor(cats));
  var n = Math.min(wantN, pool.length);
  S = {
    view: 'exam', round: 1, cats: cats, n: n,
    items: pool.slice(0, n).map(function (q) { return newItem(q.l); }),
    idx: 0, left: n * SEC_PER_Q, total: n * SEC_PER_Q,
    running: true, startedAt: Date.now(), elapsed: 0
  };
  save(); render(); startTimer();
}
function secondPass() {
  var missed = S.items.filter(function (it) { return !it.ok; });
  var labels = shuffle(missed.map(function (it) { return it.label; }));
  S.round += 1;
  S.items = labels.map(function (l) { return newItem(l); });
  S.idx = 0;
  S.total = labels.length * SEC_PER_Q;
  S.left = S.total;
  S.view = 'exam';
  S.running = true;
  save(); render(); startTimer();
}
function finish() {
  stopTimer();
  S.running = false;
  S.view = 'summary';
  save();
  render();                 /* without this the summary is never displayed */
  window.scrollTo(0, 0);
}
function startTimer() {
  stopTimer();
  tick = setInterval(function () {
    if (!S || !S.running) return;
    S.left -= 1; S.elapsed = (S.elapsed || 0) + 1;
    if (S.left <= 0) { S.left = 0; finish(); return; }
    if (S.left % 5 === 0) save();
    paintClock();
  }, 1000);
}
function stopTimer() { if (tick) { clearInterval(tick); tick = null; } }
function paintClock() {
  var c = document.getElementById('clock');
  if (!c || !S) return;
  c.textContent = mmss(S.left);
  c.className = 'clock' + (S.left <= 60 ? ' low' : '');
}

/* --------------------------------------------------------------------- views */
function viewStart() {
  var saved = loadSaved();
  var resume = saved && saved.view === 'exam' && saved.items && saved.items.length
    ? '<div class="card"><b>Unfinished session</b>' +
      '<p class="sub">' + saved.items.length + ' questions, round ' + saved.round +
      ', ' + mmss(saved.left) + ' left.</p>' +
      '<button class="btn primary block" data-act="resume">Resume where I stopped</button>' +
      '<button class="btn ghost block" data-act="discard" style="margin-top:6px">Start a new exam instead</button></div>'
    : '';
  var chips = DATA.categories.map(function (c) {
    return '<button class="chip" data-act="cat" data-cat="' + esc(c.cat) + '" aria-pressed="false">' +
      esc(c.label) + '<span class="cn">' + c.n + ' questions</span></button>';
  }).join('');
  return '' + resume +
    '<h1>PCA practice exam</h1>' +
    '<p class="sub">' + DATA.questions.length + ' gradeable questions from the ' +
    DATA.source + ' walkthrough series. Tap categories to narrow the pool, or ' +
    'leave them all off for the full bank.</p>' +
    '<h2>1. Categories</h2>' +
    '<div class="chips" id="cats">' + chips + '</div>' +
    '<p class="fact" id="avail" style="margin-top:10px"></p>' +
    '<h2>2. How many questions</h2>' +
    '<div class="card">' +
      '<div class="rowline"><input type="range" id="n" min="5" max="50" step="1" value="20">' +
      '<span class="big" id="nv">20</span></div>' +
      '<p class="fact">Time limit is the real exam ratio: <b id="ratio"></b> ' +
      '(50 questions = 120 minutes).</p>' +
    '</div>' +
    '<button class="btn primary block" data-act="start" style="margin-top:14px">Start exam</button>' +
    '<div class="card legend" style="margin-top:18px">' +
      '<b>How this works</b><br>' +
      'One question per screen, with prev / next and a jump box. The answer and ' +
      'the walkthrough explanation appear as soon as you check a question. ' +
      'Multi-answer questions say how many to pick and are graded all-or-nothing. ' +
      'Questions you miss come back as a second round at the end.<br><br>' +
      '<b>Where the content comes from</b><br>' +
      'Correct answers were read from the green highlight in the video, not guessed. ' +
      'Explanations are the presenter\u2019s spoken walkthrough, auto-transcribed, so ' +
      'they are marked <span class="asr">ASR</span> \u2014 expect misheard product names. ' +
      'The printed slide text is the reliable source.' +
    '</div>';
}

function viewExam() {
  var it = S.items[S.idx];
  var q = BY_LABEL[it.label];
  var cl = correctLetters(q);
  var need = cl.length;
  if (!it.checked) { it.revealed = it.revealed || false; }

  var options = q.o.map(function (o) {
    var pressed = it.chosen.indexOf(o.l) >= 0;
    var cls = 'opt', mark = '';
    if (it.checked) {
      var isC = cl.indexOf(o.l) >= 0, choseIt = pressed;
      if (isC) { cls += ' pick-right'; mark = 'correct'; }
      else if (choseIt) { cls += ' pick-wrong'; mark = 'your pick'; }
    }
    return '<button class="' + cls + '" data-act="opt" data-letter="' + esc(o.l) + '"' +
      ' aria-pressed="' + pressed + '"' + (it.checked ? ' disabled' : '') + '>' +
      '<span class="lt">' + esc(o.l) + '</span>' +
      '<span class="tx">' + esc(o.t) + '</span>' +
      (mark ? '<span class="mark">' + mark + '</span>' : '') +
      '</button>';
  }).join('');

  var head = '<span class="qno">Question ' + (S.idx + 1) + ' of ' + S.items.length +
    ' \u00b7 ' + esc(q.l) + (q.n ? ' \u00b7 bank #' + q.n : '') +
    (S.round > 1 ? ' \u00b7 review round ' + S.round : '') + '</span>';

  var fb = it.checked ? feedbackHTML(q, it, cl) : '';

  var jump = '<select class="jump" id="jump">' + S.items.map(function (x, i) {
    var st = x.checked ? (x.ok ? ' \u2713' : '\u2717') : '\u00b7';
    return '<option value="' + i + '"' + (i === S.idx ? ' selected' : '') + '>' +
      (i + 1) + st + '</option>';
  }).join('') + '</select>';

  return '<div class="bar"><div class="top">' +
      '<span>Question ' + (S.idx + 1) + ' / ' + S.items.length + '</span>' +
      '<span class="clock" id="clock">' + mmss(S.left) + '</span>' +
    '</div>' +
    '<div class="progress"><i style="width:' + (100 * (S.idx + 1) / S.items.length) + '%"></i></div>' +
    '</div>' +
    (S.round > 1 ? '<div class="notice">Review round: these are the ones you missed.</div>' : '') +
    (need > 1 ? '<div><span class="tag multi">Select ' + need + ' answers</span></div>' : '') +
    '<div class="stem">' + head + esc(q.stem) + '</div>' +
    options + fb +
    '<div class="actions"><div class="inner">' +
      '<button class="btn" data-act="prev"' + (S.idx === 0 ? ' disabled' : '') + '>Prev</button>' +
      jump +
      (it.checked
        ? '<button class="btn primary wide" data-act="next">' +
          (S.idx === S.items.length - 1 ? 'Finish' : 'Next') + '</button>'
        : '<button class="btn wide" data-act="reveal">Reveal</button>' +
          '<button class="btn primary" data-act="check">Check</button>') +
    '</div></div>';
}

function feedbackHTML(q, it, cl) {
  var ok = it.ok;
  var ans = cl.map(function (l) {
    return '<b>' + esc(l) + '</b>. ' + esc(optionText(q, l));
  }).join('<br>');

  var expl = (q.e || '').trim()
    ? '<div class="expl">' + esc(q.e) + '</div>'
    : '<div class="notice">No walkthrough text for this one (it comes from the part ' +
      'whose captions could not be fetched). Use the video link below.</div>';

  var concepts = (q.concepts && q.concepts.length)
    ? '<div class="fact"><b>Concepts tested:</b> ' + q.concepts.map(function (c) {
        return esc(c.name); }).join(' \u00b7 ') + '</div>'
    : '';

  var traps = (DATA.q_traps[q.l] || []);
  var trapBlock = traps.length
    ? '<div class="fact" style="margin-top:10px"><b>Traps this bank files this question under:</b></div>' +
      traps.map(function (t) {
        return '<button class="trapbtn" data-act="trap" data-slug="' + esc(t.slug) + '">' +
          esc(t.title) + '</button>';
      }).join('')
    : '';

  var watch = q.w
    ? '<div class="fact" style="margin-top:8px">Watch the walkthrough: ' +
      '<a href="' + esc(q.w) + '" target="_blank" rel="noopener">' + esc(q.w) + '</a></div>'
    : '';

  return '<div class="card fb ' + (ok ? 'ok' : 'bad') + '">' +
    '<div class="verdict">' + (ok ? '\u2713 Correct'
      : (it.revealed ? '\u25cb Revealed \u2014 counted as incorrect' : '\u2717 Incorrect')) + '</div>' +
    '<div class="answer"><b>Answer:</b><br>' + ans + '</div>' +
    '<div class="fact"><b>Walkthrough explanation</b><span class="asr">ASR</span></div>' +
    expl + concepts + trapBlock + watch +
    '</div>';
}

function viewSummary() {
  var done = S.items.filter(function (i) { return i.checked; });
  var right = S.items.filter(function (i) { return i.ok; });
  var revealed = S.items.filter(function (i) { return i.revealed; });
  var skipped = S.items.filter(function (i) { return !i.checked; });
  var pct = S.items.length ? Math.round(100 * right.length / S.items.length) : 0;

  var byCat = {};
  S.items.forEach(function (it) {
    var q = BY_LABEL[it.label];
    q.concepts.forEach(function (c) {
      byCat[c.cat] = byCat[c.cat] || { n: 0, ok: 0 };
      byCat[c.cat].n += 1;
      if (it.ok) byCat[c.cat].ok += 1;
    });
  });
  var catRows = Object.keys(byCat).sort().map(function (k) {
    var v = byCat[k];
    return '<tr><td>' + esc(k) + '</td><td class="n">' + v.ok + '/' + v.n + '</td>' +
      '<td class="n">' + Math.round(100 * v.ok / v.n) + '%</td></tr>';
  }).join('');

  var rows = S.items.map(function (it, i) {
    var q = BY_LABEL[it.label];
    var st = it.ok ? '<span class="pill ok">correct</span>'
      : (it.revealed ? '<span class="pill rev">revealed</span>'
      : (it.checked ? '<span class="pill bad">wrong</span>'
      : '<span class="pill skip">skipped</span>'));
    var mine = it.chosen.length ? it.chosen.join(',') : '\u2014';
    var w = q.w ? ' <a href="' + esc(q.w) + '" target="_blank" rel="noopener">video</a>' : '';
    return '<tr><td class="n">' + (i + 1) + '</td><td class="n">' + esc(q.l) + '</td>' +
      '<td class="n">' + esc(mine) + '</td><td class="n">' + esc(correctLetters(q).join(',')) +
      '</td><td>' + st + w + '</td></tr>';
  }).join('');

  var missed = S.items.filter(function (it) { return !it.ok; }).length;

  return '<h1>Session summary</h1>' +
    '<p class="sub">Round ' + S.round + ' \u00b7 ' + S.items.length + ' questions \u00b7 ' +
    'time used ' + mmss((S.total || 0) - S.left) + ' of ' + mmss(S.total || 0) + '</p>' +
    '<div class="card"><div class="stat">' +
      '<div><div class="n">' + right.length + '/' + S.items.length + '</div><div class="k">correct</div></div>' +
      '<div><div class="n">' + pct + '%</div><div class="k">score</div></div>' +
      '<div><div class="n">' + missed + '</div><div class="k">to review</div></div>' +
      '<div><div class="n">' + revealed.length + '</div><div class="k">revealed</div></div>' +
      (skipped.length ? '<div><div class="n">' + skipped.length + '</div><div class="k">skipped</div></div>' : '') +
    '</div></div>' +
    (missed
      ? '<button class="btn primary block" data-act="again">Practice the ' + missed + ' I missed</button>'
      : '<div class="card" style="border-left:4px solid var(--ok)">Everything correct. Nothing to review.</div>') +
    '<h2>Accuracy by category</h2><div class="card"><table><thead><tr><th>Category</th>' +
      '<th>Score</th><th>%</th></tr></thead><tbody>' + catRows + '</tbody></table>' +
      '<p class="fact" style="margin-top:8px">A category far below the others is where the ' +
      'next session should start.</p></div>' +
    '<h2>Every question</h2><div class="card" style="overflow-x:auto"><table><thead><tr>' +
      '<th>#</th><th>id</th><th>you</th><th>answer</th><th></th></tr></thead><tbody>' +
      rows + '</tbody></table></div>' +
    '<div class="actions"><div class="inner">' +
      '<button class="btn wide" data-act="home">New exam</button>' +
      '<button class="btn" data-act="clear">Clear saved</button>' +
    '</div></div>';
}

function viewTrap(slug) {
  var t = DATA.traps[slug];
  if (!t) return '<div class="sheet"><div class="body"><p>Missing trap page.</p>' +
    '<button class="btn" data-act="closetrap">Close</button></div></div>';
  return '<div class="sheet"><div class="close">' +
    '<button class="btn" data-act="closetrap">Close</button></div>' +
    '<div class="body">' + t.html + '</div></div>';
}

/* -------------------------------------------------------------------- render */
function render() {
  var app = document.getElementById('app');
  if (!S) { app.innerHTML = viewStart(); afterStart(); return; }
  if (S.view === 'exam') { app.innerHTML = viewExam(); paintClock(); return; }
  if (S.view === 'summary') { app.innerHTML = viewSummary(); return; }
  app.innerHTML = viewStart(); afterStart();
}

function afterStart() {
  var n = document.getElementById('n'), nv = document.getElementById('nv');
  if (n) {
    var upd = function () {
      nv.textContent = n.value;
      document.getElementById('ratio').textContent =
        n.value + ' questions = ' + mmss(n.value * SEC_PER_Q);
      updateAvail();
    };
    n.addEventListener('input', upd);
    upd();
  }
  updateAvail();
}

function selectedCats() {
  return Array.prototype.slice.call(document.querySelectorAll('[data-act="cat"][aria-pressed="true"]'))
    .map(function (el) { return el.dataset.cat; });
}
function updateAvail() {
  var avail = document.getElementById('avail'), n = document.getElementById('n');
  if (!avail || !n) return;
  var pool = poolFor(selectedCats()).length;
  n.max = Math.min(50, Math.max(5, pool));
  if (parseInt(n.value, 10) > parseInt(n.max, 10)) { n.value = n.max; document.getElementById('nv').textContent = n.max; }
  var capped = pool < 5;
  var shown = Math.min(parseInt(n.value, 10) || 0, pool);
  avail.innerHTML = '<b>' + pool + '</b> question' + (pool === 1 ? '' : 's') +
    ' in this selection' + (capped ? ' \u2014 too few to build an exam, add another category' : '') +
    (document.getElementById('ratio')
      ? ' \u00b7 max for this run: ' + shown : '');
}

/* --------------------------------------------------------------------- events */
document.addEventListener('click', function (e) {
  var el = e.target.closest('[data-act]');
  if (!el) return;
  var act = el.dataset.act;

  if (act === 'cat') {
    el.setAttribute('aria-pressed', el.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    updateAvail();
    return;
  }
  if (act === 'start') {
    var n = parseInt(document.getElementById('n').value, 10);
    var cats = selectedCats();
    if (poolFor(cats).length < 1) return;
    startExam(cats, n);
    return;
  }
  if (act === 'resume') { S = loadSaved() || S; render(); if (S && S.view === 'exam' && S.running) startTimer(); return; }
  if (act === 'discard') { clearSaved(); S = null; render(); return; }
  if (act === 'clear') { clearSaved(); return; }
  if (act === 'home') { stopTimer(); S = null; clearSaved(); render(); return; }

  if (act === 'opt' && S && S.view === 'exam') {
    var it = S.items[S.idx];
    if (it.checked) return;
    pickOption(it, BY_LABEL[it.label], el.dataset.letter);
    paintOptions(); save();
    return;
  }
  if (act === 'check' && S && S.view === 'exam') {
    var i2 = S.items[S.idx];
    if (!i2.chosen.length) return;
    i2.checked = true;
    i2.ok = isRight(BY_LABEL[i2.label], i2.chosen);
    save(); render(); scrollFeedback();
    return;
  }
  if (act === 'reveal' && S && S.view === 'exam') {
    var i3 = S.items[S.idx];
    i3.checked = true; i3.revealed = true; i3.ok = false;
    save(); render(); scrollFeedback();
    return;
  }
  if (act === 'next' && S && S.view === 'exam') {
    if (S.idx >= S.items.length - 1) { finish(); }
    else { S.idx += 1; save(); render(); window.scrollTo(0, 0); }
    return;
  }
  if (act === 'prev' && S && S.view === 'exam') {
    if (S.idx > 0) { S.idx -= 1; save(); render(); window.scrollTo(0, 0); }
    return;
  }
  if (act === 'again') { secondPass(); window.scrollTo(0, 0); return; }
  if (act === 'trap') {
    var d = document.createElement('div');
    d.id = 'trap-sheet';
    d.innerHTML = viewTrap(el.dataset.slug);
    document.body.appendChild(d);
    return;
  }
  if (act === 'trapnav') {
    var s = document.getElementById('trap-sheet');
    if (s) s.innerHTML = viewTrap(el.dataset.slug);
    s.scrollTop = 0;
    return;
  }
  if (act === 'closetrap') {
    var s2 = document.getElementById('trap-sheet');
    if (s2) s2.remove();
    return;
  }
});

document.addEventListener('change', function (e) {
  if (e.target && e.target.id === 'jump' && S && S.view === 'exam') {
    S.idx = parseInt(e.target.value, 10) || 0;
    save(); render(); window.scrollTo(0, 0);
  }
});

/* ----------------------------------------------------------------------- boot */
S = null;
render();
