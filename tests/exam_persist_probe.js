/* Reload probe: what a phone sees when it reopens the page mid-exam.
   Runs in pass 2 of scripts/cdp_eval.js (after a real reload). */
(function () {
  window.__errs = window.__errs || [];
  window.addEventListener('error', function (e) { window.__errs.push(String(e.message)); });
  var out = {};
  var q = function (s) { return document.querySelector(s); };

  out.freshLoadStateNull = (typeof S === 'undefined' || !S);
  out.storageWorks = (function () {
    try { return localStorage.getItem('pca-exam-v1') !== null; } catch (e) { return 'blocked'; }
  })();

  var card = q('[data-act="resume"]');
  out.resumeOffered = !!card;
  out.resumeText = card ? card.parentElement.textContent.replace(/\s+/g, ' ').slice(0, 150) : null;
  out.discardAlsoOffered = !!q('[data-act="discard"]');

  if (card) {
    card.click();
    out.afterResume = S ? ('view=' + S.view + ' items=' + S.items.length + ' idx=' + S.idx +
                           ' round=' + S.round + ' left=' + S.left) : 'S null';
    out.resumedQuestionRendered = !!q('.stem');
    out.pickSurvived = S && S.items[0] ? S.items[0].chosen.join(',') : '';
    out.clockRestored = q('#clock') ? q('#clock').textContent : null;
    out.answerable = !!q('.opt');
  }

  out.pageErrors = window.__errs.length ? window.__errs.join(' // ') : 'none';
  return JSON.stringify(out, null, 1);
})()
