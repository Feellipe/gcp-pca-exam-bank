/* Browser test: drives a full exam session in a real Chrome via real DOM clicks.
   Evaluated by scripts/cdp_eval.js. Returns a JSON report.

   Deliberately picks the questions to inspect (one with a walkthrough
   explanation, one cited by a trap page) and travels to them with the jump box,
   so the explanation and trap-sheet features are actually exercised rather than
   whoever happened to be drawn first. */
(function () {
  window.__errs = [];
  window.addEventListener('error', function (e) { window.__errs.push(String(e.message)); });
  var out = {};
  var q = function (s) { return document.querySelector(s); };
  var qa = function (s) { return document.querySelectorAll(s); };
  var goto = function (i) {
    var s = q('#jump');
    s.value = String(i);
    s.dispatchEvent(new Event('change', { bubbles: true }));
    return S.idx;
  };
  var firstUnchecked = function () {
    for (var i = 0; i < S.items.length; i++) if (!S.items[i].checked) return i;
    return -1;
  };
  var firstWith = function (pred) {
    for (var i = 0; i < S.items.length; i++) if (pred(S.items[i].label)) return i;
    return -1;
  };

  out.boot = typeof DATA + ' | ' + DATA.questions.length + ' questions | ' +
             DATA.categories.length + ' categories | ' + Object.keys(DATA.traps).length + ' traps';

  /* category toggle drives the available count */
  q('[data-act="cat"][data-cat="data"]').click();
  out.availAfterData = q('#avail').textContent;
  q('[data-act="cat"][data-cat="data"]').click();
  out.availAfterUntoggle = q('#avail').textContent;
  q('[data-act="cat"][data-cat="cost"]').click();
  out.availCostOnly = q('#avail').textContent;
  q('[data-act="cat"][data-cat="cost"]').click();

  /* 50 questions at the real exam ratio */
  var n = q('#n');
  n.value = 50;
  n.dispatchEvent(new Event('input'));
  out.ratio50 = q('#ratio').textContent;
  q('[data-act="start"]').click();
  out.started = 'view=' + S.view + ' items=' + S.items.length + ' left=' + S.left +
                's (' + (S.left / 60) + ' min)';
  out.examDom = qa('.opt').length + ' options, ' + qa('.actions .btn').length +
                ' action buttons, ' + qa('#jump option').length + ' jump entries, clock=' +
                q('#clock').textContent;
  out.noFeedbackBeforeAnswer = qa('.fb').length === 0;

  /* ---- A: a question that has a real walkthrough explanation ---- */
  var iExpl = firstWith(function (l) { return BY_LABEL[l].e && BY_LABEL[l].e.length > 500; });
  out.foundExplanationQuestion = 'index ' + iExpl;
  if (iExpl >= 0) {
    out.jumpedToExplanation = goto(iExpl);
    var itE = S.items[iExpl], qE = BY_LABEL[itE.label], clE = correctLetters(qE);
    out.multiAnswerNeeded = clE.length;
    clE.forEach(function (L) { q('[data-act="opt"][data-letter="' + L + '"]').click(); });
    out.picked = itE.chosen.join(',');
    q('[data-act="check"]').click();
    out.gradedCorrect = S.items[iExpl].ok;
    var ex = q('.expl');
    var fb = q('.fb');
    out.explanation = {
      blocks: qa('.expl').length,
      chars: ex ? ex.textContent.length : 0,
      tallestIsScrollable: ex ? ex.scrollHeight > ex.clientHeight : null,
      plainTextNotMarkup: ex ? ex.children.length === 0 : null,
      verdict: fb.querySelector('.verdict').textContent,
      asrFlag: fb.textContent.indexOf('ASR') >= 0,
      conceptsListed: fb.textContent.indexOf('Concepts tested') >= 0,
      greenOptions: qa('.opt.pick-right').length,
      optionsLocked: qa('.opt:disabled').length,
      watchLink: /youtu\.be/.test(fb.textContent)
    };
  }

  /* ---- B: a question that a trap page cites ---- */
  var iTrap = firstWith(function (l) { return DATA.q_traps[l] && DATA.q_traps[l].length; });
  out.foundTrapQuestion = 'index ' + iTrap;
  if (iTrap >= 0) {
    out.jumpedToTrap = goto(iTrap);
    var itT = S.items[iTrap], qT = BY_LABEL[itT.label];
    q('[data-act="opt"][data-letter="' + qT.o[0].l + '"]').click();
    q('[data-act="check"]').click();
    out.trapButtons = qa('.trapbtn').length;
    var tb = q('.trapbtn');
    if (tb) {
      out.trapSlug = tb.getAttribute('data-slug');
      tb.click();
      var sh = document.getElementById('trap-sheet');
      out.trapSheet = sh ? {
        headings: sh.querySelectorAll('h2,h3').length,
        bullets: sh.querySelectorAll('li').length,
        quotes: sh.querySelectorAll('blockquote').length,
        chars: sh.textContent.length,
        rawMarkdownLeaked: sh.textContent.indexOf('##') >= 0 || sh.textContent.indexOf('[[') >= 0,
        asrFlag: sh.textContent.indexOf('ASR') >= 0,
        xrefsPlain: sh.querySelectorAll('.xref').length
      } : 'MISSING';
      var navLink = sh && sh.querySelector('a.tl');
      if (navLink) {
        out.trapNav = 'clicking "' + navLink.getAttribute('data-slug') + '"';
        navLink.click();
        out.trapNavWorked = !!document.getElementById('trap-sheet');
      }
      var cl = q('[data-act="closetrap"]');
      if (cl) { cl.click(); out.trapClosed = !document.getElementById('trap-sheet'); }
    }
  }

  /* ---- C: reveal counts as incorrect and says so ---- */
  var iFree = firstUnchecked();
  if (iFree >= 0) {
    out.jumpedToReveal = goto(iFree);
    q('[data-act="reveal"]').click();
    out.reveal = {
      revealed: S.items[iFree].revealed, ok: S.items[iFree].ok,
      verdict: q('.fb .verdict').textContent,
      greenShown: qa('.opt.pick-right').length
    };
  }

  /* ---- D: a wrong answer is marked, with the right one shown ---- */
  iFree = firstUnchecked();
  if (iFree >= 0) {
    out.jumpedToWrong = goto(iFree);
    var it2 = S.items[iFree], q2 = BY_LABEL[it2.label];
    var bad = q2.o.map(function (o) { return o.l; })
                  .filter(function (l) { return correctLetters(q2).indexOf(l) < 0; });
    q('[data-act="opt"][data-letter="' + bad[0] + '"]').click();
    q('[data-act="check"]').click();
    out.wrong = {
      ok: S.items[iFree].ok,
      verdict: q('.fb .verdict').textContent,
      redOptions: qa('.opt.pick-wrong').length,
      greenOptions: qa('.opt.pick-right').length
    };
  }

  /* ---- E: finish from the last question ---- */
  goto(S.items.length - 1);
  q('[data-act="reveal"]').click();
  out.nextLabel = (qa('.actions .btn').length ? qa('.actions .btn')[qa('.actions .btn').length - 1].textContent : '');
  q('[data-act="next"]').click();
  out.view = S.view;
  out.summary = {
    heading: q('h1') ? q('h1').textContent : null,
    statCells: qa('.stat .n').length,
    tableRows: qa('table tr').length,
    categoryBreakdown: document.body.textContent.indexOf('Accuracy by category') >= 0,
    reviewButton: !!q('[data-act="again"]'),
    pills: { ok: qa('.pill.ok').length, bad: qa('.pill.bad').length,
             rev: qa('.pill.rev').length, skip: qa('.pill.skip').length }
  };

  /* ---- F: review round re-asks only what was missed ---- */
  q('[data-act="again"]').click();
  out.reviewRound = 'round=' + S.round + ' items=' + S.items.length + ' idx=' + S.idx +
                    ' view=' + S.view;
  out.reviewIsSubset = S.items.every(function (it) { return !it.ok; });

  /* leave an unfinished session WITH a pick, so the reload probe can verify it */
  if (S.view === 'exam') {
    var it3 = S.items[S.idx], q3 = BY_LABEL[it3.label];
    q('[data-act="opt"][data-letter="' + q3.o[0].l + '"]').click();
    out.leftUnfinished = 'items=' + S.items.length + ' round=' + S.round +
                         ' pickedOnQ0=' + S.items[0].chosen.join(',');
    out.expectedResume = { items: S.items.length, round: S.round,
                           pick: S.items[0].chosen.join(',') };
  }

  out.pageErrors = window.__errs.length ? window.__errs.join(' // ') : 'none';
  return JSON.stringify(out, null, 1);
})()
