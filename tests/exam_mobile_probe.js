/* Phone-width layout + storage probe. Run against the file:// URL with Chrome
   launched at --window-size=390,844 to imitate a phone viewport. */
(function () {
  var out = {};
  var q = function (s) { return document.querySelector(s); };

  /* Does progress survive a reload when the page is opened as a local FILE?
     This is exactly how a phone will open it from mail/Files. */
  try {
    localStorage.setItem('__probe', '1');
    out.localStorage = (localStorage.getItem('__probe') === '1') ? 'works' : 'silently failed';
    localStorage.removeItem('__probe');
  } catch (e) {
    out.localStorage = 'BLOCKED (' + e.name + ')';
  }

  var de = document.documentElement;
  out.viewport = window.innerWidth + 'x' + window.innerHeight;
  out.pageOverflowsHorizontally = de.scrollWidth > window.innerWidth + 1
    ? (de.scrollWidth + 'px > ' + window.innerWidth + 'px') : 'no';

  /* any element sticking out past the right edge? */
  var worst = null, w = 0;
  Array.prototype.forEach.call(document.querySelectorAll('body *'), function (el) {
    var r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > window.innerWidth + 1 && r.width > w) {
      w = r.width; worst = el.tagName + (el.className ? '.' + el.className : '');
    }
  });
  out.widestOverflowingElement = worst ? worst + ' (' + Math.round(w) + 'px)' : 'none';

  /* tap targets should clear ~44px for a thumb */
  var small = [];
  Array.prototype.forEach.call(document.querySelectorAll('button, select, input'), function (el) {
    var r = el.getBoundingClientRect();
    if (r.height > 0 && r.height < 44) {
      small.push((el.className || el.tagName) + '=' + Math.round(r.height) + 'px');
    }
  });
  out.controlsUnder44px = small.length ? small.join(', ') : 'none';

  out.baseFontPx = getComputedStyle(document.body).fontSize;
  out.stickyHeader = getComputedStyle(q('.bar') || document.body).position;
  out.fixedActionBar = getComputedStyle(q('.actions') || document.body).position;
  return JSON.stringify(out, null, 1);
})()
