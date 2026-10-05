/* Verification harness: executes the SHIPPED exam.js against the JSON payload
   actually embedded in the exported HTML, with a minimal DOM stub.
   Run: node work/exam_harness.js                                            */
'use strict';
const fs = require('fs');
const vm = require('vm');
const ROOT = require('path').resolve(__dirname, '..');

const html = fs.readFileSync(ROOT + '/exam-app/pca-exam.html', 'utf8');
const m = html.match(/<script id="exam-data" type="application\/json">([\s\S]*?)<\/script>/);
if (!m) { console.error('FAIL: no embedded data block'); process.exit(1); }
const payload = m[1];

/* Payload must be valid JSON as embedded (this catches escaping mistakes) */
let data;
try { data = JSON.parse(payload); }
catch (e) { console.error('FAIL: embedded JSON does not parse -> ' + e.message); process.exit(1); }

let fails = 0, passes = 0;
function ok(name, cond, extra) {
  if (cond) { passes++; console.log('PASS  ' + name); }
  else { fails++; console.log('FAIL  ' + name + (extra !== undefined ? '  [' + extra + ']' : '')); }
}

/* --------------------------------------------------------------- DOM stub */
function mkEl(id) {
  return {
    id: id, textContent: '', innerHTML: '', className: '', value: '20', max: 50,
    dataset: {}, style: {},
    setAttribute: function () {}, getAttribute: function () { return 'false'; },
    addEventListener: function () {}, appendChild: function () {}, remove: function () {},
    closest: function () { return null; }, querySelectorAll: function () { return []; },
    dispatchEvent: function () {}
  };
}
const els = {};
global.document = {
  getElementById: function (id) { return els[id] || (els[id] = mkEl(id)); },
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  addEventListener: function () {}, createElement: function () { return mkEl('tmp'); },
  body: { appendChild: function () {} }
};
global.window = { scrollTo: function () {} };
global.localStorage = { getItem: function () { return null; }, setItem: function () {},
                        removeItem: function () {} };
global.setInterval = function () { return 0; };
global.clearInterval = function () {};
els['exam-data'] = { textContent: payload };

/* Run the shipped app code in the global context so its functions are reachable */
vm.runInThisContext(fs.readFileSync(ROOT + '/exam-app/assets/exam.js', 'utf8'));
const g = globalThis;

/* --------------------------------------------------------------- payload */
const Q = g.DATA.questions;
ok('payload parses; 323 gradeable questions', Q.length === 323, Q.length);
ok('no duplicate labels in the bank', new Set(Q.map(q => q.l)).size === Q.length);
ok('every question has >=2 options', Q.every(q => q.o.length >= 2));
ok('every question has a stem', Q.every(q => (q.stem || '').trim().length > 10));
ok('every answer letter exists in its own options', Q.every(q => {
  const ls = q.o.map(o => o.l);
  return q.correct.split(',').every(c => ls.indexOf(c) >= 0);
}));
ok('no repeated question text (duplicates excluded)', (function () {
  const seen = new Set();
  for (const q of Q) {
    const k = q.stem.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 120);
    if (seen.has(k)) return false;
    seen.add(k);
  }
  return true;
})());
ok('all 37 multi-answer questions kept', Q.filter(q => q.correct.split(',').length > 1).length === 37);
ok('303 questions carry an explanation', Q.filter(q => q.e.trim()).length === 303,
   Q.filter(q => q.e.trim()).length);
ok('20 questions without explanation (part 1 captions)', Q.filter(q => !q.e.trim()).length === 20);
ok('every question has a video deep link',
   Q.every(q => /^https:\/\/youtu\.be\/[A-Za-z0-9_-]+\?t=\d+$/.test(q.w || '')));
ok('categories present with counts', g.DATA.categories.length === 11, g.DATA.categories.length);
ok('per-question time = 144s (50q:120min)', g.DATA.per_question_seconds === 144);

/* --------------------------------------------------------------- grading */
const q1 = Q[0];
ok('isRight true for the exact answer set', g.isRight(q1, q1.correct.split(',')) === true);
ok('isRight false for an empty pick', g.isRight(q1, []) === false);
const mq = Q.filter(x => x.correct.split(',').length > 1)[0];
ok('multi-answer needs EVERY letter',
   g.isRight(mq, [mq.correct.split(',')[0]]) === false);
ok('multi-answer is order-insensitive',
   g.isRight(mq, mq.correct.split(',').reverse()) === true);
const wrongOf = x => x.o.map(o => o.l).filter(l => x.correct.split(',').indexOf(l) < 0);
ok('isRight false when a wrong letter is included',
   g.isRight(q1, wrongOf(q1).slice(0, 1)) === false);
ok('isRight false for the wrong letter on a multi-answer question',
   g.isRight(mq, wrongOf(mq).slice(0, 1)) === false);

/* ------------------------------------------------------ selection rules */
const singleQ = Q.filter(x => x.correct.split(',').length === 1)[0];
let it = { chosen: [] };
g.pickOption(it, singleQ, 'A');
g.pickOption(it, singleQ, 'B');
ok('single answer replaces the previous pick', it.chosen.join(',') === 'B', it.chosen.join(','));
g.pickOption(it, singleQ, 'B');
ok('tapping a selected option deselects it', it.chosen.length === 0);
it = { chosen: [] };
const need2 = Q.filter(x => x.correct.split(',').length === 2)[0];
g.pickOption(it, need2, 'A'); g.pickOption(it, need2, 'B');
ok('two picks held for a "select 2" question', it.chosen.join(',') === 'A,B', it.chosen.join(','));
g.pickOption(it, need2, 'C');
ok('a third pick pushes out the oldest (capped at 2)', it.chosen.join(',') === 'B,C', it.chosen.join(','));

/* ----------------------------------------------------------- pooling */
const pool = g.poolFor(['data']);
ok('category pool is non-empty and all-match',
   pool.length > 0 && pool.every(q => q.concepts.some(c => c.cat === 'data')), pool.length);
ok('no selection = the whole bank', g.poolFor([]).length === 323);
ok('two categories union their pools',
   g.poolFor(['data', 'compute']).length >= pool.length);
ok('a tiny category still returns its questions', g.poolFor(['cost']).length === 4,
   g.poolFor(['cost']).length);

/* -------------------------------------------------------- session + views */
g.startExam(['compute', 'data'], 10);
ok('session built 10 items', g.S.items.length === 10, g.S.items.length);
ok('session pools only the chosen categories',
   g.S.items.every(x => g.BY_LABEL[x.label].concepts.some(c => c.cat === 'compute' || c.cat === 'data')));
ok('timer = 10 x 144 = 1440s', g.S.left === 1440 && g.S.total === 1440, g.S.left);
ok('session starts in exam view and running', g.S.view === 'exam' && g.S.running === true);
ok('requesting more than available is capped', (function () {
  g.startExam(['cost'], 50); const n = g.S.items.length; return n === 4;
})(), g.S.items.length);

g.startExam(['data'], 5);
it = g.S.items[0];
const qq = g.BY_LABEL[it.label];
it.chosen = g.correctLetters(qq); it.checked = true; it.ok = true;
let h = g.viewExam();
ok('a correct pick renders green', h.indexOf('pick-right') >= 0);
ok('correct verdict shown', h.indexOf('fb ok') >= 0 && h.indexOf('Correct') >= 0);
ok('no Reveal button once checked', h.indexOf('data-act="reveal"') < 0);
ok('Next button offered after checking', h.indexOf('data-act="next"') >= 0);
ok('jump select has one entry per question', (h.match(/<option/g) || []).length === 5,
   (h.match(/<option/g) || []).length);

g.S.idx = 1;
it = g.S.items[1];
const q2 = g.BY_LABEL[it.label];
it.chosen = wrongOf(q2).slice(0, 1); it.checked = true; it.ok = false;
h = g.viewExam();
ok('a wrong pick renders red', h.indexOf('pick-wrong') >= 0);
ok('the correct option is still revealed in green', h.indexOf('pick-right') >= 0);
ok('incorrect verdict shown', h.indexOf('fb bad') >= 0 && h.indexOf('Incorrect') >= 0);
ok('the answer is spelled out', h.indexOf('Answer:') >= 0);
ok('explanation block or placeholder present',
   h.indexOf('class="expl"') >= 0 || h.indexOf('No walkthrough text') >= 0);
ok('explanation is flagged ASR', h.indexOf('ASR') >= 0);
ok('a video deep link is offered', h.indexOf('youtu.be') >= 0);

const rq = q2;
const revealFb = g.feedbackHTML(rq, { checked: true, revealed: true, ok: false },
                               g.correctLetters(rq));
ok('revealing is labelled and counted incorrect', revealFb.indexOf('Revealed') >= 0);

/* feedback must carry concepts, traps and the video link */
const trapped = Q.filter(x => g.DATA.q_traps[x.l] && g.DATA.q_traps[x.l].length);
ok('some questions carry trap links', trapped.length > 0, trapped.length);
if (trapped.length) {
  const tq = trapped[0];
  const fb = g.feedbackHTML(tq, { checked: true, revealed: false, ok: false },
                            g.correctLetters(tq));
  ok('trap buttons appear in feedback', fb.indexOf('trapbtn') >= 0);
  ok('trap button carries a real slug',
     fb.indexOf('data-slug="' + g.DATA.q_traps[tq.l][0].slug + '"') >= 0);
  ok('concepts tested are listed',
     tq.concepts.length === 0 || fb.indexOf('Concepts tested') >= 0);
}
const noExpl = Q.filter(x => !x.e.trim());
ok('a question with no walkthrough shows the placeholder, not a blank',
   g.feedbackHTML(noExpl[0], { checked: true, revealed: false, ok: false },
                  g.correctLetters(noExpl[0])).indexOf('No walkthrough text') >= 0);

/* ------------------------------------------------------------- summary */
g.startExam([], 6);
g.S.items[0].chosen = ['A']; g.S.items[0].checked = true; g.S.items[0].ok = true;
g.S.items[1].chosen = ['A']; g.S.items[1].checked = true; g.S.items[1].ok = false;
g.S.items[2].chosen = []; g.S.items[2].checked = true; g.S.items[2].revealed = true;
let sum = g.viewSummary();
ok('summary renders', sum.indexOf('Session summary') >= 0);
ok('summary shows the score fraction', sum.indexOf('1/6') >= 0);
ok('summary breaks accuracy down by category', sum.indexOf('Accuracy by category') >= 0);
ok('summary lists every question', (sum.match(/<tr>/g) || []).length >= 6);
ok('summary flags a revealed question', sum.indexOf('revealed') >= 0);
ok('summary flags a skipped question', sum.indexOf('skipped') >= 0);
ok('offers a review round of the missed ones', sum.indexOf('data-act="again"') >= 0);

const missedLabels = g.S.items.filter(x => !x.ok).map(x => x.label);
g.secondPass();
ok('review round returns every question not answered correctly (wrong, revealed and skipped)',
   g.S.items.length === missedLabels.length && g.S.items.length === 5, g.S.items.length);
ok('review round holds exactly those labels',
   g.S.items.every(x => missedLabels.indexOf(x.label) >= 0));
ok('review round increments the round counter', g.S.round === 2, g.S.round);
ok('review round resets the index', g.S.idx === 0);

/* Regression: finish() used to set the state without rendering, so finishing the
   exam (or the clock expiring) left the last question on screen forever. */
g.startExam([], 3);
els['app'].innerHTML = '';
g.finish();
ok('finishing renders the summary rather than only setting state',
   g.S.view === 'summary' && String(els['app'].innerHTML).indexOf('Session summary') >= 0);
ok('finishing stops the clock', g.S.running === false);

/* --------------------------------------------------------- trap pages */
const slugs = Object.keys(g.DATA.traps);
ok('5 trap pages embedded', slugs.length === 5, slugs.length);
let trapProblems = [];
slugs.forEach(function (s) {
  const t = g.DATA.traps[s];
  if (!t.title || t.html.length < 200) trapProblems.push(s + ': thin content');
  if (t.html.indexOf('##') >= 0) trapProblems.push(s + ': raw markdown heading');
  if (t.html.indexOf('[[') >= 0) trapProblems.push(s + ': unrendered wikilink');
  (t.html.match(/data-slug="([a-z0-9-]+)"/g) || []).forEach(function (x) {
    const target = x.slice(11, -1);
    if (!g.DATA.traps[target]) trapProblems.push(s + ': link to missing trap ' + target);
  });
});
ok('trap pages render cleanly and link only to real pages',
   trapProblems.length === 0, trapProblems.join('; '));
ok('trap HTML contains the ASR flag convention',
   slugs.some(s => g.DATA.traps[s].html.indexOf('ASR') >= 0));
const knownLabels = new Set(Q.map(q => q.l));
const orphan = Object.keys(g.DATA.q_traps).filter(l => !knownLabels.has(l));
ok('every trap question reference exists in the app bank', orphan.length === 0,
   orphan.join(','));

/* ------------------------------------------------------------- helpers */
ok('mmss(144) = 2:24', g.mmss(144) === '2:24', g.mmss(144));
ok('mmss(7200) = 2:00:00', g.mmss(7200) === '2:00:00', g.mmss(7200));
ok('mmss(9) = 0:09', g.mmss(9) === '0:09', g.mmss(9));

/* ------------------------------------------------- self-containment audit */
/* Scan the MARKUP only: the inlined script text contains JS string fragments
   like 'href="' + esc(q.w) + '"' that are not real references. */
const markup = html.replace(/<script[\s\S]*?<\/script>/g, '')
                   .replace(/<style[\s\S]*?<\/style>/g, '');
const externals = (markup.match(/(?:src|href)="([^"]*)"/g) || [])
  .filter(x => !/="(?:data:|#)/.test(x));
ok('markup references no external file (works offline)', externals.length === 0,
   externals.join(','));
/* URLs quoted inside a walkthrough are content, not dependencies - so check the
   fields the APP controls, and prove content can never be interpreted as markup. */
const appOnly = JSON.stringify(data, function (k, v) {
  return (k === 'stem' || k === 't' || k === 'e' || k === 'html') ? '' : v;
});
const urls = appOnly.match(/https?:\/\/[^"\\]+/g) || [];
ok('URLs in app-controlled fields are only youtu.be deep links',
   urls.length > 0 && urls.every(u => u.indexOf('https://youtu.be/') === 0), urls.join(','));
ok('esc() neutralises HTML', g.esc('<img src=x onerror=alert(1)>').indexOf('<') < 0);
const evil = { n: 1, l: 'evil', stem: '<img src=x onerror=alert(1)>',
               o: [{ l: 'A', t: '<script>bad()</script>' }], correct: 'A',
               concepts: [], w: '', e: '<b>hi</b><img src=x>' };
const evilHtml = g.feedbackHTML(evil, { checked: true, revealed: false, ok: false }, ['A']);
ok('hostile slide/transcript text cannot inject markup into feedback',
   evilHtml.indexOf('<img') < 0 && evilHtml.indexOf('<script') < 0);
const withUrl = Q.filter(x => x.o.some(o => /https?:\/\//.test(o.t)));
ok('a real option quotes a URL (option in ' + (withUrl[0] ? withUrl[0].l : 'none') + ')',
   withUrl.length > 0, withUrl.length);
g.startExam([], 1);
g.S.items = [{ label: withUrl[0].l, chosen: [], checked: false, revealed: false, ok: null }];
g.S.idx = 0;
const urlView = g.viewExam();
ok('an option quoting a URL renders as escaped text, not a live link',
   urlView.indexOf('status.cloud.google.com') >= 0 &&
   urlView.indexOf('<a href="https://status') < 0);
ok('no leftover template tokens', html.indexOf('__EXAM_') < 0 && html.indexOf('/*__') < 0);
ok('CSS and JS were inlined',
   html.indexOf('.opt.pick-right') >= 0 && html.indexOf('function pickOption') >= 0);

console.log('\n' + passes + ' passed, ' + fails + ' failed');
process.exit(fails ? 1 : 0);
