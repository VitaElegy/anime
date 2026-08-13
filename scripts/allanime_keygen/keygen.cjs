// AllAnime/mkissa client-crypto key deriver v2 (adapted for live 2026-08 chunk).
// Args: <refr_url> <cdn_immutable_base>. Emits KEY/EPOCH/BUILDID/LANE lines.
// Proxy from env AA_PROXY (default http://127.0.0.1:7892).
'use strict';
const { ProxyAgent, fetch: undiciFetch, setGlobalDispatcher } = require('undici');
const AA_PROXY = process.env.AA_PROXY || 'http://127.0.0.1:7892';
setGlobalDispatcher(new ProxyAgent(AA_PROXY));
const rawFetch = undiciFetch;
// All requests (site fetches AND the evaluated crypto chunk's window.fetch)
// go through this wrapper so accept-encoding never advertises zstd. The CDN
// answers zstd over HTTP/2 when it is advertised, and Node 23 cannot
// decompress zstd ('createZstdDecompress is not a function').
globalThis.fetch = async (url, opts = {}) => {
  const headers = new Headers(opts.headers || {});
  if (!headers.has('accept-encoding')) headers.set('accept-encoding', 'gzip, deflate, br');
  return rawFetch(url, { ...opts, headers });
};
const fs = require('fs');

const ARGV = process.argv.slice(2);
const refr = ARGV[0], cdn = ARGV[1];
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0';
const ENC = new TextEncoder();
function OUT(s){ process.stdout.write(s); }
function EXIT(c){ process.exit(c); }
function die(m){ process.stderr.write('aa-keygen-v2: ' + m + '\n'); EXIT(1); }
async function get(url){
  var r = await fetch(url, { headers: { 'User-Agent': UA, 'Referer': refr } });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
  return await r.text();
}
async function findCryptoChunk(){
  var landing = await get(refr);
  var re = new RegExp(cdn.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + '/entry/app\\.[A-Za-z0-9_.-]+\\.js');
  var appUrl = (landing.match(re) || [])[0];
  if (!appUrl) throw new Error('app.js not found on landing page');
  var app = await get(appUrl);
  var seen = {}, chunks = [], m, cr = /"[.][.]\/chunks\/([A-Za-z0-9_.-]+\.js)"/g;
  while ((m = cr.exec(app))) { if (!seen[m[1]]) { seen[m[1]] = 1; chunks.push(m[1]); } }
  for (var i = 0; i < chunks.length; i++) {
    var js = await get(cdn + '/chunks/' + chunks[i]);
    if (js.indexOf('client-crypto/v1/bootstrap') !== -1) return js;
  }
  throw new Error('crypto chunk not found (site structure changed)');
}
function loadModule(src){
  var importNames = {}, m, ir = /import\{([^}]*)\}from"[^"]*";?/g;
  while ((m = ir.exec(src))) {
    var parts = m[1].split(',');
    for (var i = 0; i < parts.length; i++) {
      var seg = parts[i].trim(), as = / as (\w+)$/.exec(seg);
      if (as) importNames[as[1]] = 1; else if (/^\w+$/.test(seg)) importNames[seg] = 1;
    }
  }
  src = src.replace(/import\{[^}]*\}from"[^"]*";?/g, '')
           .replace(/export\{[^}]*\};?\s*$/g, '')
           .replace(/import\.meta/g, '({url:"x",env:{}})');
  var importDecls = Object.keys(importNames).map(function(n){ return 'let ' + n + '=__mk();'; }).join('');
  var host = new URL(refr).host, origin = new URL(refr).origin;
  var store = '{_d:{},getItem(k){return this._d[k]??null},setItem(k,v){this._d[k]=String(v)},removeItem(k){delete this._d[k]},clear(){this._d={}},key(){return null},get length(){return 0}}';
  var harness = '"use strict";\n'
    + 'const __mk=()=>new Proxy(function(){return __mk()},{get(t,p){if(p===Symbol.iterator)return function*(){};if(p===\'then\')return undefined;return __mk()},apply(){return __mk()},construct(){return __mk()}});\n'
    + 'const localStorage=(' + store + '),sessionStorage=(' + store + ');\n'
    + 'const location={host:' + JSON.stringify(host) + ',hostname:' + JSON.stringify(host) + ',origin:' + JSON.stringify(origin) + ',href:' + JSON.stringify(refr + '/') + ',protocol:"https:",pathname:"/",search:""};\n'
    + 'const navigator={userAgent:' + JSON.stringify(UA) + ',language:"en",languages:["en"]};\n'
    + 'const document={currentScript:null,cookie:"",addEventListener(){},removeEventListener(){},createElement(){return{style:{},setAttribute(){},appendChild(){}}},documentElement:{style:{}},head:{appendChild(){}},body:{appendChild(){}},querySelector(){return null},getElementById(){return null}};\n'
    + 'const window=new Proxy({location,navigator,document,localStorage,sessionStorage,addEventListener(){},removeEventListener(){},matchMedia(){return{matches:false,addEventListener(){}}},setTimeout,clearTimeout,setInterval,clearInterval,fetch:globalThis.fetch,crypto:globalThis.crypto,atob:globalThis.atob,btoa:globalThis.btoa},{get(t,p){return p in t?t[p]:__mk()}});\n'
    + 'const self=window;\n'
    + importDecls + '\n' + src + '\n'
    + ';return { $I:(typeof $I!=="undefined"?$I:undefined), LI:(typeof LI!=="undefined"?LI:undefined), UI:(typeof UI!=="undefined"?UI:undefined), Im:(typeof Im!=="undefined"?Im:undefined), NI:(typeof NI!=="undefined"?NI:undefined), T_:(typeof T_!=="undefined"?T_:undefined), CI:(typeof CI!=="undefined"?CI:undefined), EI:(typeof EI!=="undefined"?EI:undefined), getEpoch:()=>typeof ba!=="undefined"?ba:null, getBuildId:()=>typeof kr!=="undefined"?kr:null, getLane:()=>typeof Sm!=="undefined"?Sm:null, Jn:(typeof Jn!=="undefined"?Jn:null), b_:(typeof b_!=="undefined"?b_:null) };';
  return new Function(harness)();
}
(async function(){
  if (!refr || !cdn) die('usage: <refr_url> <cdn_immutable_base>');
  var src; try { src = await findCryptoChunk(); } catch(e){ die(e.message); }
  fs.writeFileSync('/tmp/live_crypto_chunk.js', src);
  var M; try { M = loadModule(src); } catch(e){ die('module load failed: ' + e.message); }
  if (typeof M.LI !== 'function') die('LI entrypoint missing (crypto logic changed)');
  process.stderr.write('debug: kr=' + M.kr + ' Sm=' + M.Sm + ' Jn=' + (M.Jn && M.Jn()) + '\n');
  var keyBytes = null, lastErr = null;
  try { keyBytes = await M.LI(1, M.Sm || 'k7'); }
  catch(e){ lastErr = e; }
  if (!keyBytes || keyBytes.length !== 32) die('bootstrap failed: ' + (lastErr && lastErr.message));
  var hex = Array.from(new Uint8Array(keyBytes)).map(function(x){ return x.toString(16).padStart(2,'0'); }).join('');
  var epoch = M.getEpoch();
  try { var boot = await M.CI(M.getLane() || 'k7'); process.stderr.write('BOOT json=' + JSON.stringify(boot) + '\n'); } catch(e){ process.stderr.write('BOOT err: ' + (e && e.message) + '\n'); }
  if (epoch == null) die('epoch not resolved');
  var buildId = M.getBuildId();
  if (!buildId) die('build id not resolved');
  OUT('KEY=' + hex + '\nEPOCH=' + epoch + '\nBUILDID=' + buildId + '\nLANE=' + (M.getLane() || 'k7') + '\n');
  EXIT(0);
})().catch(function(e){ die('unexpected: ' + (e && e.message || e)); });
