/* Minimal CDP driver: loads a URL in a real Chrome and evaluates JS in the page.
 *
 * Exists because the agent's browser backend needs its own Chromium build, while
 * a system Chrome is already installed. Node 22 has a global fetch and WebSocket,
 * so this needs no dependencies.
 *
 * Usage:
 *   chrome --headless=new --remote-debugging-port=9222 --user-data-dir=<tmp> about:blank
 *   node scripts/cdp_eval.js <url> <js-file> [reload-js-file]
 *
 * Prints the value the JS expression returns, and optionally reloads the page and
 * evaluates a second file (used to test state that survives a reload).
 */
'use strict';
const fs = require('fs');

const args = process.argv.slice(2).filter((a) => a.indexOf('--') !== 0);
const url = args[0];
const jsFile = args[1];
const reloadJsFile = args[2] || null;
if (!url || !jsFile) {
  console.error('usage: node cdp_eval.js <url-or-path> <js-file> [reload-js-file] [--emulate=WxH]');
  process.exit(2);
}
const code = fs.readFileSync(jsFile, 'utf8');
const emulateArg = process.argv.find((a) => a.indexOf('--emulate=') === 0);
const emulate = emulateArg ? emulateArg.split('=')[1] : null;   // e.g. 390x844

/* A bare path is resolved against this machine and turned into a file:// URL, so
   the same command works from any clone instead of hardcoding an absolute path. */
let pageUrl = url;
if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(pageUrl)) {
  const abs = require('path').resolve(pageUrl).replace(/\\/g, '/');
  pageUrl = 'file:///' + abs.replace(/^\/+/, '');
}

class Conn {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); }
  async open() {
    await new Promise((res, rej) => {
      this.ws.addEventListener('open', res, { once: true });
      this.ws.addEventListener('error', (e) => rej(new Error('ws error')), { once: true });
    });
    this.ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) { this.pending.get(msg.id)(msg); this.pending.delete(msg.id); }
    });
  }
  send(method, params) {
    const id = ++this.id;
    return new Promise((res) => {
      this.pending.set(id, res);
      this.ws.send(JSON.stringify({ id: id, method: method, params: params || {} }));
    });
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (r.error) throw new Error('CDP error: ' + JSON.stringify(r.error));
    if (r.result && r.result.exceptionDetails) {
      const d = r.result.exceptionDetails;
      throw new Error('page exception: ' + ((d.exception && d.exception.description) || d.text));
    }
    return r.result ? r.result.result.value : undefined;
  }
  close() { try { this.ws.close(); } catch (e) { /* ignore */ } }
}

async function target(url) {
  const base = 'http://127.0.0.1:9222';
  try {
    const r = await fetch(base + '/json/new?' + encodeURIComponent(url), { method: 'PUT' });
    if (r.ok) return await r.json();
  } catch (e) { /* fall through to reusing a tab */ }
  const list = await (await fetch(base + '/json/list')).json();
  const page = list.find((t) => t.type === 'page');
  if (!page) throw new Error('no page target available');
  return page;
}

async function ready(c, tries) {
  for (let i = 0; i < (tries || 150); i++) {
    try {
      const st = await c.eval('document.readyState + "|" + (typeof DATA === "undefined" ? "noapp" : "app")');
      if (st === 'complete|app') { await new Promise((r) => setTimeout(r, 250)); return true; }
    } catch (e) { /* context may not exist yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  return false;
}

function show(label, v) {
  console.log('--- ' + label + ' ---');
  console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 1));
}

(async () => {
  const t = await target(pageUrl);
  const c = new Conn(t.webSocketDebuggerUrl);
  await c.open();
  await c.send('Runtime.enable');
  await c.send('Page.enable');
  if (emulate) {
    const wh = emulate.split('x').map(Number);
    await c.send('Emulation.setDeviceMetricsOverride', {
      width: wh[0], height: wh[1], deviceScaleFactor: 3, mobile: true
    });
    await new Promise((r) => setTimeout(r, 400));    // let the layout reflow
  }
  if (!(await ready(c))) throw new Error('page never became ready / app script did not run');
  show('pass 1', await c.eval(code));
  if (reloadJsFile) {
    await c.send('Page.reload', { ignoreCache: true });
    if (!(await ready(c))) throw new Error('page did not reload cleanly');
    show('pass 2 (after reload)', await c.eval(fs.readFileSync(reloadJsFile, 'utf8')));
  }
  c.close();
  process.exit(0);
})().catch((e) => { console.error('DRIVER ERROR: ' + e.message); process.exit(1); });
