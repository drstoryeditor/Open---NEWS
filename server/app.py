#!/usr/bin/env python3
"""Open - News · site server + admin desk.  v3

Fixes in this version
---------------------
1. Sessions survive server restarts (stateless signed tokens derived from
   ADMIN_PASSWORD) — publishing can no longer hang on a dead session.
2. All admin APIs return proper JSON errors; the page shows real messages
   ("session expired — enter passphrase again") instead of spinning forever.
3. Archive labels: optional. Blank label auto-becomes  Weekly Edition (30 August 2026).
   Labels display exactly as typed (kept in archives/manifest.json).
4. Full permissions: the desk can list, load, save, upload and delete ANY file
   in site/ (index, paper, archives, images — everything).
"""
import hashlib, hmac, json, os, re, secrets, threading, time
from datetime import datetime
from pathlib import Path

from flask import (Flask, abort, jsonify, make_response, redirect,
                   request, send_from_directory)

BASE = Path(__file__).resolve().parent
SITE = BASE.parent / 'site'
ARCH = SITE / 'archives'
MANIFEST = ARCH / 'manifest.json'

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
SESSION_TTL = 12 * 3600

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024   # 64 MB uploads
FAILS = {}   # ip -> [count, lock_until]
WRITE_LOCK = threading.Lock()   # serialises publish/upload/save/delete

# ---------------- stateless sessions (survive restarts) ----------------

def _key():
    return hashlib.sha256(('opennews::' + ADMIN_PASSWORD).encode()).digest()

def make_token():
    ts = str(int(time.time()))
    sig = hmac.new(_key(), ts.encode(), hashlib.sha256).hexdigest()
    return ts + '.' + sig

def valid_session():
    if not ADMIN_PASSWORD:
        return False
    tok = request.cookies.get('deskid', '')
    if '.' not in tok:
        return False
    ts, sig = tok.split('.', 1)
    good = hmac.new(_key(), ts.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return (time.time() - int(ts)) < SESSION_TTL
    except ValueError:
        return False

# ---------------- rate limiting ----------------

def client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '?').split(',')[0].strip()

def locked_out(ip):
    rec = FAILS.get(ip)
    if not rec:
        return False
    count, until = rec
    if until and time.time() < until:
        return True
    if until and time.time() >= until:
        FAILS.pop(ip, None)
    return False

def register_fail(ip):
    count, until = FAILS.get(ip, [0, 0])
    count += 1
    FAILS[ip] = [count, time.time() + 900] if count >= 5 else [count, 0]

def noindex(resp):
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store'
    return resp

# ---------------- archive machinery ----------------

def load_manifest():
    try:
        return json.loads(MANIFEST.read_text(encoding='utf-8'))
    except Exception:
        return {}

def save_manifest(m):
    ARCH.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding='utf-8')

def default_label():
    return 'Weekly Edition (' + datetime.now().strftime('%d %B %Y') + ')'

def archive_current(label):
    src = SITE / 'paper.html'
    if not src.exists():
        return None
    label = (label or '').strip() or default_label()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    fname = f'{stamp}.html'
    i = 1
    while (ARCH / fname).exists():
        fname = f'{stamp}-{i}.html'
        i += 1
    ARCH.mkdir(exist_ok=True)
    (ARCH / fname).write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
    m = load_manifest()
    m[fname] = label
    save_manifest(m)
    rebuild_archive_index()
    return label

def rebuild_archive_index():
    m = load_manifest()
    rows = []
    for f in sorted(ARCH.glob('*.html'), reverse=True):
        label = m.get(f.name)
        if not label:
            stamp = f.name.split('.', 1)[0].split('_', 1)[0]
            try:
                label = 'Weekly Edition (' + datetime.strptime(stamp, '%Y%m%d-%H%M%S').strftime('%d %B %Y') + ')'
            except ValueError:
                label = f.name
        stem = f.name.split('.', 1)[0].split('_', 1)[0]
        stem = re.sub(r'-\d+$', '', stem) if len(stem) > 15 else stem
        try:
            nice = datetime.strptime(stem, '%Y%m%d-%H%M%S').strftime('%d %B %Y')
        except ValueError:
            nice = ''
        rows.append(f'<li><a href="archives/{f.name}">{label}</a>'
                    f'<span class="d">archived {nice}</span></li>')
    listing = '\n'.join(rows) if rows else '<li class="none">No archived editions yet. The first archive appears when a new edition replaces this week&rsquo;s.</li>'
    (SITE / 'archives.html').write_text(ARCHIVE_TPL.replace('__ROWS__', listing), encoding='utf-8')

ARCHIVE_TPL = '''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open - News &middot; Archives</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:#100e0c; }
#stage { width:900px; transform-origin:top left; }
.page { width:900px; background:#fbf8ef; color:#151310; padding:40px 48px;
  font-family:Georgia, 'Times New Roman', serif; min-height:600px; }
h1 { font-size:52px; text-align:center; border-bottom:3px double #151310; padding-bottom:14px; }
.sub { text-align:center; font-style:italic; color:#4d463a; padding:10px 0 24px 0; }
ul { list-style:none; }
li { padding:12px 4px; border-bottom:1px dotted #bdb298; font-size:18px; }
li a { color:#8f1d1d; text-decoration:none; font-weight:bold; }
li a:hover { color:#151310; }
li .d { float:right; color:#77705f; font-size:14px; font-style:italic; }
li.none { color:#4d463a; font-style:italic; }
.back { display:block; text-align:center; margin-top:28px; font-size:15px; }
.back a { color:#151310; }
</style></head>
<body><div id="stage"><div class="page">
<h1>The Archives</h1>
<div class="sub">Every past edition of Open - News, kept the way a library keeps its Sundays.</div>
<ul>
__ROWS__
</ul>
<span class="back"><a href="index.html">&larr; back to the front page</a></span>
</div></div>
<script>
(function(){
  var s = document.getElementById('stage');
  function refit(){
    s.style.transform='none'; s.style.marginLeft='0';
    var w = s.getBoundingClientRect().width;
    var vw = document.documentElement.clientWidth;
    var sc = Math.min(1, vw / w);
    s.style.transformOrigin='top left';
    s.style.transform='scale('+sc+')';
    s.style.marginLeft = Math.max(0,(vw-w*sc)/2)+'px';
    document.body.style.height=(s.scrollHeight*sc)+'px';
    document.body.style.overflowX='hidden';
  }
  window.addEventListener('resize',refit); window.addEventListener('load',refit); refit();
})();
</script></body></html>'''

# ---------------- public site ----------------

@app.route('/')
def home():
    return send_from_directory(SITE, 'index.html')

@app.route('/<path:name>')
def public(name):
    if name == 'archives/manifest.json':
        abort(404)
    target = (SITE / name).resolve()
    if not str(target).startswith(str(SITE.resolve())):
        abort(404)
    if target.is_file():
        return send_from_directory(SITE, name)
    abort(404)

# ---------------- admin: login ----------------

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    ip = client_ip()
    if request.method == 'POST' and not valid_session():
        if not ADMIN_PASSWORD:
            return noindex(make_response(page_login('ADMIN_PASSWORD is not set on the server.'), 500))
        if locked_out(ip):
            return noindex(make_response(page_login('Too many attempts. The desk is closed for 15 minutes.'), 429))
        if hmac.compare_digest(request.form.get('pw', ''), ADMIN_PASSWORD):
            FAILS.pop(ip, None)
            resp = make_response(redirect('/admin'))
            resp.set_cookie('deskid', make_token(), httponly=True, samesite='Strict', max_age=SESSION_TTL)
            return noindex(resp)
        register_fail(ip)
        return noindex(make_response(page_login('Wrong passphrase.'), 401))
    if valid_session():
        return noindex(make_response(page_desk()))
    return noindex(make_response(page_login('')))

@app.route('/admin/logout')
def logout():
    resp = make_response(redirect('/'))
    resp.delete_cookie('deskid')
    return noindex(resp)

# ---------------- admin: APIs — always JSON, never redirects ----------------

def guard():
    """Return a JSON 401 response if session invalid, else None."""
    if not valid_session():
        return noindex(make_response(jsonify(ok=False, error='session expired — reload the page and enter the passphrase again'), 401))
    return None

def safe_site_path(name):
    """Resolve a user-supplied path inside site/; None if it escapes."""
    if not name or name.startswith('/') or '..' in name:
        return None
    target = (SITE / name).resolve()
    if not str(target).startswith(str(SITE.resolve())):
        return None
    return target

TEXT_EXT = {'.html', '.htm', '.css', '.js', '.json', '.txt', '.svg', '.xml', '.md'}
PROTECTED = {'index.html', 'paper.html', 'archives.html'}

@app.route('/admin/api/publish', methods=['POST'])
def api_publish():
    if (g := guard()):
        return g
    f = request.files.get('file')
    if not f or not f.filename:
        return noindex(jsonify(ok=False, error='no file chosen'))
    try:
        html = f.read().decode('utf-8', errors='replace')
    except Exception as e:
        return noindex(jsonify(ok=False, error=f'could not read file: {e}'))
    if '<html' not in html.lower():
        return noindex(jsonify(ok=False, error='that file does not look like an HTML paper'))
    do_archive = request.form.get('archive', '1') != '0'
    try:
        with WRITE_LOCK:
            label = archive_current(request.form.get('label', '')) if do_archive else None
            (SITE / 'paper.html').write_text(html, encoding='utf-8')
    except Exception as e:
        return noindex(jsonify(ok=False, error=f'server error while publishing: {e}'))
    if do_archive:
        return noindex(jsonify(ok=True, archived=label or 'nothing to archive'))
    return noindex(jsonify(ok=True, archived=None))

@app.route('/admin/api/list')
def api_list():
    if (g := guard()):
        return g
    files = []
    for f in sorted(SITE.rglob('*')):
        if f.is_file() and f.name != 'manifest.json':
            rel = str(f.relative_to(SITE))
            files.append({'name': rel, 'size': f.stat().st_size,
                          'protected': rel in PROTECTED})
    return noindex(jsonify(ok=True, files=files))

@app.route('/admin/api/file', methods=['GET', 'POST'])
def api_file():
    if (g := guard()):
        return g
    if request.method == 'GET':
        name = request.args.get('name', '')
        target = safe_site_path(name)
        if not target or not target.is_file():
            return noindex(jsonify(ok=False, error='file not found'))
        if target.suffix.lower() not in TEXT_EXT:
            return noindex(jsonify(ok=False, error='binary file — use upload to replace it'))
        return noindex(jsonify(ok=True, content=target.read_text(encoding='utf-8', errors='replace')))
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name', '')
    target = safe_site_path(name)
    if not target:
        return noindex(jsonify(ok=False, error='invalid path'))
    if target.suffix.lower() not in TEXT_EXT:
        return noindex(jsonify(ok=False, error='only text files can be saved here'))
    try:
        with WRITE_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data.get('content', ''), encoding='utf-8')
            if str(target).startswith(str(ARCH.resolve())):
                rebuild_archive_index()
    except Exception as e:
        return noindex(jsonify(ok=False, error=f'save failed: {e}'))
    return noindex(jsonify(ok=True))

@app.route('/admin/api/upload', methods=['POST'])
def api_upload():
    if (g := guard()):
        return g
    f = request.files.get('file')
    name = request.form.get('name', '') or (f.filename if f else '')
    if not f:
        return noindex(jsonify(ok=False, error='no file chosen'))
    target = safe_site_path(name)
    if not target:
        return noindex(jsonify(ok=False, error='invalid destination path'))
    try:
        with WRITE_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            f.save(target)
            if str(target).startswith(str(ARCH.resolve())):
                rebuild_archive_index()
    except Exception as e:
        return noindex(jsonify(ok=False, error=f'upload failed: {e}'))
    return noindex(jsonify(ok=True, saved=name))

@app.route('/admin/api/delete', methods=['POST'])
def api_delete():
    if (g := guard()):
        return g
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name', '')
    if name in PROTECTED:
        return noindex(jsonify(ok=False, error='core page — edit it instead of deleting'))
    target = safe_site_path(name)
    if not target or not target.is_file():
        return noindex(jsonify(ok=False, error='file not found'))
    try:
        with WRITE_LOCK:
            target.unlink()
            m = load_manifest()
            if target.name in m:
                m.pop(target.name)
                save_manifest(m)
            if name.startswith('archives/'):
                rebuild_archive_index()
    except Exception as e:
        return noindex(jsonify(ok=False, error=f'delete failed: {e}'))
    return noindex(jsonify(ok=True))

# ---------------- admin pages ----------------

STYLE = '''
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:#100e0c; }
#stage { width:960px; transform-origin:top left; }
.page { width:960px; background:#fbf8ef; color:#151310; padding:38px 46px 30px 46px;
  font-family:Georgia, 'Times New Roman', serif; }
.topline { border-top:3px solid #151310; border-bottom:1px solid #151310; padding:5px 0;
  font-size:11px; letter-spacing:4px; text-transform:uppercase; text-align:center; color:#8f1d1d;
  font-family:Verdana, sans-serif; }
h1.mast { font-size:56px; text-align:center; padding:14px 0 4px 0; font-weight:normal; }
h1.mast .dash { color:#8f1d1d; }
.tag { text-align:center; font-style:italic; font-size:14px; color:#3c362c;
  border-bottom:3px double #151310; padding-bottom:12px; }
.kicker { font-family:Verdana, sans-serif; font-size:10px; letter-spacing:3px; text-transform:uppercase;
  color:#8f1d1d; border-bottom:1px solid #151310; padding-bottom:4px; margin:24px 0 10px 0; }
p.note { font-size:14px; color:#4d463a; font-style:italic; margin-bottom:10px; line-height:1.45; }
input[type=password], input[type=text] { width:100%; padding:10px; font-size:15px;
  font-family:Georgia, serif; border:1.5px solid #151310; background:#fff; margin-bottom:12px; }
input[type=file] { font-size:13px; margin-bottom:12px; font-family:Georgia, serif; }
textarea { width:100%; height:340px; font-family:Consolas, monospace; font-size:12px;
  border:1.5px solid #151310; background:#fff; padding:10px; margin-top:8px; }
button { padding:10px 26px; font-family:Verdana, sans-serif; font-size:12px; letter-spacing:2px;
  text-transform:uppercase; background:#151310; color:#f2ecd7; border:2px solid #151310;
  cursor:pointer; margin-right:8px; margin-bottom:6px; }
button:hover { background:#8f1d1d; border-color:#8f1d1d; }
button.ghost { background:transparent; color:#151310; }
button.ghost:hover { color:#8f1d1d; border-color:#8f1d1d; }
button.mini { padding:4px 10px; font-size:10px; margin:0 0 0 8px; }
.msg { font-size:13px; font-style:italic; }
.ok { color:#1d6b2a; } .bad { color:#8f1d1d; }
ul.files { list-style:none; font-size:13px; }
ul.files li { padding:6px 2px; border-bottom:1px dotted #bdb298; display:flex; align-items:center; }
ul.files li .fn { flex:1; }
ul.files li .sz { color:#77705f; font-size:11px; margin-left:8px; }
.foot { border-top:3px double #151310; margin-top:26px; padding-top:8px; font-family:Verdana, sans-serif;
  font-size:10px; letter-spacing:2px; text-transform:uppercase; color:#3c362c; display:flex; justify-content:space-between; }
.foot a { color:#8f1d1d; text-decoration:none; }
.err { border:2px solid #8f1d1d; color:#8f1d1d; padding:9px 12px; font-size:14px; margin-bottom:14px; }
'''

FIT_JS = '''<script>
(function(){
  var s = document.getElementById('stage');
  function refit(){
    s.style.transform='none'; s.style.marginLeft='0';
    var w = s.getBoundingClientRect().width;
    var vw = document.documentElement.clientWidth;
    var sc = Math.min(1, vw / w);
    s.style.transformOrigin='top left';
    s.style.transform='scale('+sc+')';
    s.style.marginLeft = Math.max(0,(vw-w*sc)/2)+'px';
    document.body.style.height=(s.scrollHeight*sc)+'px';
    document.body.style.overflowX='hidden';
  }
  window.addEventListener('resize',refit); window.addEventListener('load',refit); refit();
})();
</script>'''

def page_login(err):
    errhtml = f'<div class="err">{err}</div>' if err else ''
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Open - News &middot; The Desk</title>
<style>{STYLE}</style></head>
<body><div id="stage"><div class="page">
  <div class="topline">The Editor&rsquo;s Desk &middot; Private</div>
  <h1 class="mast">Open <span class="dash">-</span> News</h1>
  <div class="tag">&ldquo;The room behind the printing press.&rdquo;</div>
  <div class="kicker">Entry &middot; Passphrase Required</div>
  {errhtml}
  <form method="post">
    <input type="password" name="pw" placeholder="passphrase" autofocus autocomplete="off">
    <button>Enter the desk</button>
  </form>
  <p class="note">The passphrase is set in the server&rsquo;s environment (ADMIN_PASSWORD).
  Change it on Render&rsquo;s dashboard or in run.bat &mdash; never in code.</p>
  <div class="foot"><span>Open - News</span><a href="/">&larr; front page</a></div>
</div></div>{FIT_JS}</body></html>'''

def page_desk():
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Open - News &middot; The Desk</title>
<style>{STYLE}</style></head>
<body><div id="stage"><div class="page">
  <div class="topline">The Editor&rsquo;s Desk &middot; Private</div>
  <h1 class="mast">Open <span class="dash">-</span> News</h1>
  <div class="tag">&ldquo;The room behind the printing press.&rdquo;</div>

  <div class="kicker">One &middot; Publish This Week&rsquo;s Paper</div>
  <p class="note"><b>Publish &amp; archive</b> — the normal Sunday flow: the edition currently live moves
  to the Archives shelf (blank label becomes &ldquo;Weekly Edition (today&rsquo;s date)&rdquo;), then the new paper goes live.<br>
  <b>Publish only</b> — replaces the live paper <em>without</em> archiving; use it for corrections
  to the current edition so the shelf doesn&rsquo;t fill with drafts.</p>
  <input type="text" id="label" placeholder="Archive label (optional) — default: Weekly Edition (date)">
  <input type="file" id="file" accept=".html,.htm">
  <div>
    <button onclick="publish(true)">Publish &amp; archive</button>
    <button class="ghost" onclick="publish(false)">Publish only</button>
    <span id="pubmsg" class="msg"></span>
  </div>

  <div class="kicker">Two &middot; Edit Any File</div>
  <p class="note">Type a path (e.g. index.html &middot; paper.html &middot; archives/20260830-0339.html), load, edit, save.</p>
  <input type="text" id="fname" value="index.html">
  <div>
    <button class="ghost" onclick="loadFile()">Load</button>
    <button onclick="saveFile()">Save</button>
    <span id="editmsg" class="msg"></span>
  </div>
  <textarea id="content" spellcheck="false" placeholder="— file contents appear here —"></textarea>

  <div class="kicker">Three &middot; Upload Any File</div>
  <p class="note">Replace or add any file — images, extra pages, anything. Destination path is optional;
  by default the file keeps its own name at the site root.</p>
  <input type="text" id="upname" placeholder="Destination path (optional) — e.g. images/logo.jpg">
  <input type="file" id="upfile">
  <div><button onclick="uploadFile()">Upload</button><span id="upmsg" class="msg"></span></div>

  <div class="kicker">Four &middot; Everything On The Shelf</div>
  <p class="note">Core pages are protected from deletion (edit them instead). Archives and other files can be deleted.</p>
  <ul class="files" id="filelist"><li>loading&hellip;</li></ul>

  <div class="foot"><span>Open - News &middot; The Desk</span>
  <span><a href="/">&larr; front page</a> &nbsp;&middot;&nbsp; <a href="/paper.html">current paper</a> &nbsp;&middot;&nbsp; <a href="/admin/logout">sign out</a></span></div>
</div></div>{FIT_JS}
<script>
function setMsg(id, text, good){{
  const m = document.getElementById(id);
  m.textContent = ' ' + text;
  m.className = 'msg ' + (good ? 'ok' : 'bad');
}}
async function call(url, opts){{
  try {{
    const r = await fetch(url, opts);
    let j;
    try {{ j = await r.json(); }}
    catch(e) {{ return {{ok:false, error:'unexpected server reply (' + r.status + ') — reload the page and log in again'}}; }}
    return j;
  }} catch(e) {{
    return {{ok:false, error:'network error — ' + e.message}};
  }}
}}
async function publish(doArchive){{
  const f = document.getElementById('file').files[0];
  if(!f){{ setMsg('pubmsg','choose a file first',false); return; }}
  if(!doArchive && !confirm('Publish WITHOUT archiving? The current live edition will be overwritten and not kept on the shelf.')) return;
  setMsg('pubmsg','publishing…',true);
  const fd = new FormData();
  fd.append('file', f);
  fd.append('label', document.getElementById('label').value);
  fd.append('archive', doArchive ? '1' : '0');
  const j = await call('/admin/api/publish', {{method:'POST', body:fd}});
  setMsg('pubmsg', j.ok ? (j.archived ? ('published — previous edition archived as “' + j.archived + '”')
                                      : 'published — live paper replaced (nothing archived)') : j.error, j.ok);
  if(j.ok) listFiles();
}}
async function loadFile(){{
  const n = document.getElementById('fname').value.trim();
  const j = await call('/admin/api/file?name=' + encodeURIComponent(n));
  if(j.ok){{ document.getElementById('content').value = j.content; setMsg('editmsg','loaded ' + n, true); }}
  else setMsg('editmsg', j.error, false);
}}
async function saveFile(){{
  const n = document.getElementById('fname').value.trim();
  const j = await call('/admin/api/file', {{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{name:n, content:document.getElementById('content').value}})}});
  setMsg('editmsg', j.ok ? 'saved ' + n : j.error, j.ok);
  if(j.ok) listFiles();
}}
async function uploadFile(){{
  const f = document.getElementById('upfile').files[0];
  if(!f){{ setMsg('upmsg','choose a file first',false); return; }}
  const fd = new FormData();
  fd.append('file', f);
  fd.append('name', document.getElementById('upname').value.trim() || f.name);
  setMsg('upmsg','uploading…',true);
  const j = await call('/admin/api/upload', {{method:'POST', body:fd}});
  setMsg('upmsg', j.ok ? 'saved as ' + j.saved : j.error, j.ok);
  if(j.ok) listFiles();
}}
async function delFile(name){{
  if(!confirm('Delete ' + name + ' permanently?')) return;
  const j = await call('/admin/api/delete', {{method:'POST',
    headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{name:name}})}});
  if(!j.ok) alert(j.error);
  listFiles();
}}
function fmtSize(b){{
  return b > 1048576 ? (b/1048576).toFixed(1) + ' MB' : b > 1024 ? (b/1024).toFixed(0) + ' KB' : b + ' B';
}}
async function listFiles(){{
  const j = await call('/admin/api/list');
  if(!j.ok){{ document.getElementById('filelist').innerHTML = '<li>' + j.error + '</li>'; return; }}
  const ul = document.getElementById('filelist');
  ul.innerHTML = '';
  for (const f of j.files) {{
    const li = document.createElement('li');
    const fn = document.createElement('span'); fn.className = 'fn'; fn.textContent = f.name;
    const sz = document.createElement('span'); sz.className = 'sz'; sz.textContent = fmtSize(f.size);
    li.appendChild(fn); li.appendChild(sz);
    if (!f.protected) {{
      const b = document.createElement('button');
      b.className = 'mini'; b.textContent = 'delete';
      b.addEventListener('click', () => delFile(f.name));
      li.appendChild(b);
    }}
    ul.appendChild(li);
  }}
}}
listFiles();
</script></body></html>'''

@app.errorhandler(401)
def unauth(e):
    return noindex(make_response(redirect('/admin')))

@app.errorhandler(404)
def nf(e):
    return make_response('Not found', 404)

@app.errorhandler(413)
def toobig(e):
    return noindex(make_response(jsonify(ok=False, error='file too large (max 64 MB)'), 413))

rebuild_archive_index()   # runs on import (gunicorn) too

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
