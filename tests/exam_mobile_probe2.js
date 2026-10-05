/* Phone-layout probe, run INSIDE an exam (the sticky header and action bar only
   exist there). Checks that a long explanation does not break the layout, that
   the action bar stays reachable at the bottom of the screen, and that every
   control clears a thumb-sized tap target.
   Run: node scripts/cdp_eval.js <url> work/exam_mobile_probe2.js --emulate=390x844 */
(function () {
  var out = {};
  var q = function (s) { return document.querySelector(s); };

  var n = q('#n');
  n.value = 5;
  n.dispatchEvent(new Event('input'));
  q('[data-act="start"]').click();

  /* go to the question with the longest explanation - the worst case for layout */
  var idx = 0, longest = -1;
  for (var i = 0; i < S.items.length; i++) {
    var len = BY_LABEL[S.items[i].label].e.length;
    if (len > longest) { longest = len; idx = i; }
  }
  var s = q('#jump');
  s.value = String(idx);
  s.dispatchEvent(new Event('change', { bubbles: true }));
  var it = S.items[S.idx], qq = BY_LABEL[it.label];
  correctLetters(qq).forEach(function (L) {
    q('[data-act="opt"][data-letter="' + L + '"]').click();
  });
  q('[data-act="check"]').click();

  /* scroll to the very bottom, as a user reading the explanation would */
  window.scrollTo(0, document.body.scrollHeight);

  var bar = q('.bar'), act = q('.actions');
  var ar = act.getBoundingClientRect(), br = bar.getBoundingClientRect();
  out.viewport = window.innerWidth + 'x' + window.innerHeight;
  out.explanationChars = q('.expl') ? q('.expl').textContent.length : 0;

  out.stickyHeader = {
    position: getComputedStyle(bar).position,
    pinnedToTop: Math.abs(br.top) < 2,
    clockVisible: br.top >= -1 && br.bottom <= window.innerHeight
  };
  out.fixedActionBar = {
    position: getComputedStyle(act).position,
    fullyOnScreen: ar.top >= 0 && ar.bottom <= window.innerHeight + 1,
    bottomPx: Math.round(ar.bottom),
    viewportHeight: window.innerHeight,
    stillClickable: (function () {
      var b = q('.actions .btn').getBoundingClientRect();
      return b.top >= 0 && b.bottom <= window.innerHeight + 1 && b.width > 40;
    })()
  };

  var de = document.documentElement;
  out.horizontalOverflow = de.scrollWidth > window.innerWidth + 1
    ? (de.scrollWidth + 'px > ' + window.innerWidth + 'px') : 'no';

  var small = [];
  Array.prototype.forEach.call(document.querySelectorAll('button, select, input'), function (el) {
    var r = el.getBoundingClientRect();
    if (r.height > 0 && r.height < 44) {
      small.push((el.className || el.tagName) + '=' + Math.round(r.height) + 'px');
    }
  });
  out.controlsUnder44px = small.length ? small.join(', ') : 'none';
  out.optionRowHeight = q('.opt') ? Math.round(q('.opt').getBoundingClientRect().height) + 'px' : null;
  out.actionButtons = Array.prototype.map.call(
    document.querySelectorAll('.actions .btn'),
    function (b) { return b.textContent + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' +
                          Math.round(b.getBoundingClientRect().height); }).join(', ');
  out.attributeList = (function () {
    var f = document.body.textContent.match(/Bank #[0-9]+/);
    return f ? f[0] : 'n/a';
  })();
  return JSON.stringify(out, null, 1);
})()
