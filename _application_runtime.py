if '_settings' not in globals():
 raise RuntimeError('Use application.create_app to initialize this private runtime')
import os, sqlite3, smtplib, shutil, threading, time, secrets, re, io, csv, zipfile, ssl, socket, html, base64, hashlib, ipaddress
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from flask import has_request_context, abort, g, Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from authorization import directory_scope_sql, ticket_scope_sql, directory_can_edit_target, asset_scope_sql, service_write_scope_sql, service_read_scope_sql, can_delegate_user, STAFF_ROLES

from app_config import flask_configuration
BASE=os.path.dirname(os.path.abspath(__file__))
DB=_settings.get('ITSM_DB') or os.path.join(BASE,'itsm.db')
BACKUPS=_backup_dir
os.makedirs(BACKUPS,exist_ok=True)
app=Flask('app',root_path=BASE)
app.config.update(flask_configuration(_settings,_secret_key,_testing))

from database import Database, RequestConnection, AUDIT_INSERT
_database=Database(app,lambda:DB,lambda connection:commit_request_connection(connection))

def db():
 return _database.connection()

@app.teardown_request
def close_request_connections(error=None):
 return _database.close_request(error)

def cols(c,t): return [r['name'] for r in c.execute(f'PRAGMA table_info({t})')]
def preflight_db():
 from migrations import inspect_database
 return inspect_database(DB)

def init_db():
 from migrations import run_migrations
 return run_migrations(DB,_settings.get('ITSM_INITIAL_ADMIN_PASSWORD',''))


def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
ROLES=['System Administrator','Service Owner','Service Desk Manager','Operational Operator','Central Administrator','Local Administrator','Management','Requester','Auditor']
GLOBAL=('System Administrator','Service Owner','Service Desk Manager','Operational Operator','Central Administrator','Management','Auditor')
ORG=None   # set by org.init for organizational visibility
WRITE=('System Administrator','Service Owner','Service Desk Manager','Operational Operator','Central Administrator','Local Administrator')
PRIOS=('Low','Medium','High','Critical'); TYPES=('Service Request','Task'); FAILS={}
TRANS={'Open':['Assigned','In Progress','Waiting','Closed'],'Assigned':['In Progress','Waiting'],'In Progress':['Waiting','Resolved'],'Waiting':['In Progress'],'Resolved':['Closed','In Progress'],'Closed':[]}
# ===================== v8.5 helpers =====================
PALETTE=['#2f80ed','#27ae60','#f2994a','#9b51e0','#eb5757','#00acc1','#c9a227','#e91e8c','#5c6bc0','#43a047','#8d6e63','#00897b']
DEFAULT_SENDER='notifications@example.invalid'
EMAIL_RE=re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
PHONE_RE=re.compile(r'^[0-9+()\-\s./]{5,30}$')
SMTP_KEYS=['smtp_host','smtp_port','smtp_user','smtp_password','smtp_sender','smtp_from_name','smtp_security','smtp_verify','base_url']

def add_business_hours(start,hours):
    """Add working hours, excluding Saturdays and Sundays from SLA calculations."""
    cur=start; rem=timedelta(hours=hours)
    while rem>timedelta(0):
        if cur.weekday()>=5:
            cur=(cur+timedelta(days=7-cur.weekday())).replace(hour=0,minute=0,second=0,microsecond=0); continue
        eod=(cur+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        step=min(rem,eod-cur); cur+=step; rem-=step
    return cur

def pdt(s):
    if not s: return None
    s=str(s).replace('T',' ')
    for fmt,n in (('%Y-%m-%d %H:%M:%S',19),('%Y-%m-%d %H:%M',16),('%Y-%m-%d',10)):
        try: return datetime.strptime(s[:n],fmt)
        except ValueError: continue
    return None

def vis_ticket_sql(u,a='t'):
    c=db()
    try:
        return ticket_scope_sql(u,ORG,c,a)
    finally:
        c.close()


def visible_users(c,rows):
 scope,args=directory_scope_sql(current(),ORG,c)
 ids={r[0] for r in c.execute('SELECT u.id FROM users u WHERE '+scope,args)}
 return [r for r in rows if r['id'] in ids]


def visible_services(c,rows):
 scope,args=service_read_scope_sql(current(),ORG,c)
 ids={r[0] for r in c.execute('SELECT s.id FROM services s WHERE '+scope,args)}
 return [r for r in rows if r['id'] in ids]


def scoped_service_counts(c, rows):
    scope, args = ticket_scope_sql(current(), ORG, c)
    counts = {r['service_id']: r['n'] for r in c.execute(
        "SELECT t.service_id,count(*) n FROM tickets t WHERE " + scope +
        " AND t.status NOT IN ('Resolved','Closed') GROUP BY t.service_id", args)}
    service_scope,service_args=service_read_scope_sql(current(),ORG,c)
    child_counts={r['parent_service_id']:r['n'] for r in c.execute('SELECT s.parent_service_id,count(*) n FROM services s WHERE '+service_scope+' AND s.is_main=0 GROUP BY s.parent_service_id',service_args)}
    return [dict(r, open_count=counts.get(r['id'],0),subsection_count=child_counts.get(r['id'],0)) for r in visible_services(c,rows)]




@app.before_request
def _csrf():
 if request.method=='POST':
  tok=session.get('csrf'); sent=request.form.get('csrf_token') or request.headers.get('X-CSRF')
  if not isinstance(tok,str) or not isinstance(sent,str) or not tok or not sent or not tok.isascii() or not sent.isascii() or not secrets.compare_digest(tok,sent): return 'Invalid CSRF token. Refresh the page.',403
@app.before_request
def validate_mutation_input():
 if request.method!='POST': return
 if request.is_json:
  data=request.get_json(silent=True)
  if not isinstance(data,dict): return 'JSON object required',400
  for key in ('to','with','list_id'):
   if key in data and (isinstance(data[key],bool) or not str(data[key]).isascii() or not str(data[key]).isdigit() or int(data[key])<=0): return 'Invalid identifier',400
  if 'body' in data and not isinstance(data['body'],str): return 'Invalid message',400
 else:
  for key in request.form:
   identifier=key.endswith('_id') or key in ('id','step_user')
   if (identifier or key in ('action','form','role','csrf_token')) and len(request.form.getlist(key))>1: return 'Duplicate parameter',400
   value=request.form[key]
   if identifier and value and (not value.isascii() or not value.isdigit() or int(value)<=0): return 'Invalid identifier',400

@app.errorhandler(ValueError)
def invalid_value(error): return 'Invalid request value',400

@app.context_processor
def _csrfctx():
 if 'csrf' not in session: session['csrf']=secrets.token_hex(16)
 return {'csrf_token':lambda:session['csrf']}
@app.after_request
def _hdr(r):
 r.headers.update({'Content-Security-Policy':"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store'})
 if app.config['SESSION_COOKIE_SECURE']: r.headers['Strict-Transport-Security']='max-age=31536000'
 return r


def commit_request_connection(connection): connection.commit()


@app.after_request
def finish_request_transaction(response):
 return _database.finish(response)

@app.errorhandler(sqlite3.IntegrityError)
def _ie(e):
 _database.rollback()
 flash('Already exists or invalid data.','danger'); return redirect(safe_back(url_for('dashboard')))
@app.errorhandler(KeyError)
def _ke(e): return 'Invalid request',400
def current():
 if 'cu' not in g:
  c=db(); g.cu=c.execute('SELECT * FROM users WHERE id=? AND active=1',(session.get('uid'),)).fetchone(); c.close()
 return g.cu
def can_view(c,t):
    sql,args=ticket_scope_sql(current(),ORG,c,'t')
    return bool(c.execute('SELECT 1 FROM tickets t WHERE t.id=? AND '+sql,[t['id'],*args]).fetchone())

ASSET_ROLES=('System Administrator','Central Administrator','Service Owner','Service Desk Manager')
DIR_EDIT=('System Administrator','Central Administrator')
def can_write(c,t):
    u=current()
    if not can_view(c,t): return False
    role=u['role']
    if role not in STAFF_ROLES and role!='Requester': return False
    if role=='Requester':
        return t['requester_id']==u['id']
    return role in WRITE or t['assignee_id']==u['id'] or bool(c.execute(
        'SELECT 1 FROM ticket_steps WHERE ticket_id=? AND user_id=?',(t['id'],u['id'])).fetchone())

def mine_sql(a='t'):
 return (f"({a}.requester_id=? OR {a}.assignee_id=? OR {a}.created_by=? OR EXISTS(SELECT 1 FROM tasks ta1 JOIN task_assignees x1 ON x1.task_id=ta1.id WHERE ta1.ticket_id={a}.id AND x1.user_id=?) OR EXISTS(SELECT 1 FROM ticket_steps st1 WHERE st1.ticket_id={a}.id AND st1.user_id=?))",)
TYPE_TITLES={'Incident':'Incidents','Problem':'Problems','Change':'Changes','Task':'Task tickets','Service Request':'Service requests'}
def login_required(f):
 @wraps(f)
 def w(*a,**k):
  if 'uid' not in session or not current() or session.get('auth_version')!=current()['auth_version']: session.clear(); return redirect(url_for('login'))
  if current()['role'] not in ROLES: return 'Access Denied',403
  session['role']=current()['role']
  issued=session.get('issued_at')
  if not isinstance(issued,(int,float)) or issued>time.time()+30 or time.time()-issued>8*3600: session.clear(); return redirect(url_for('login'))
  if current()['must_change'] and request.endpoint not in ('account','logout'): flash('You must change your password before continuing.','danger'); return redirect(url_for('account'))
  return f(*a,**k)
 return w

def setting(k,d=''):
 c=db(); r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone(); c.close(); return r['value'] if r else d
def audit(a,o,oid,old='',new=''):
 values=(session.get('uid'),a,o,oid,str(old),str(new),request.remote_addr if request else '',now())
 _database.stage_audit(values)
 c=db(); c.execute(AUDIT_INSERT,values); c.commit(); c.close()
def event(tid,typ,details):
 c=db(); c.execute('INSERT INTO timeline(ticket_id,actor_id,event_type,details,created_at) VALUES(?,?,?,?,?)',(tid,session.get('uid'),typ,details,now())); c.commit(); c.close()
def notify(uid,title,message,link='',kind='info'):
 c=db(); c.execute('INSERT INTO notifications(user_id,title,message,link,kind,created_at) VALUES(?,?,?,?,?,?)',(uid,title,message,link,kind,now())); c.commit(); c.close()
# ---------------- Email / njoftime (v8.5) ----------------
def base_url():
    b=setting('base_url','').strip().rstrip('/')
    if b: return b
    try: return request.host_url.rstrip('/')
    except RuntimeError: return ''
def _fernet():
    try:
        from cryptography.fernet import Fernet
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('itsm-smtp|'+app.secret_key).encode()).digest()))
    except Exception: return None
def enc_secret(v):
    f=_fernet()
    return ('enc:'+f.encrypt(v.encode()).decode()) if (f and v) else v
def dec_secret(v):
    if v and v.startswith('enc:'):
        f=_fernet()
        try: return f.decrypt(v[4:].encode()).decode()
        except Exception: return ''
    return v
def log_mail(to,subject,ok,msg):
    try:
        c=db(); c.execute('INSERT INTO email_log(to_addr,subject,ok,message,created_at) VALUES(?,?,?,?,?)',(to,str(subject)[:200],1 if ok else 0,str(msg)[:300],now())); c.commit(); c.close()
    except Exception: pass
def send_async(to,subject,body,html_body=None):
 _database.dispatch_after_commit(send_email,to,subject,body,html_body)

def send_email(to,subject,body,html_body=None):
    host=setting('smtp_host'); user=setting('smtp_user'); pwd=dec_secret(setting('smtp_password')); sender=setting('smtp_sender','').strip() or DEFAULT_SENDER; name=setting('smtp_from_name','OpenITSM Ticket System') or 'OpenITSM'
    try: port=int(setting('smtp_port','25') or 25)
    except ValueError: port=25
    subject=' '.join(str(subject).split())[:200]
    if not host: log_mail(to,subject,False,'SMTP is not configured.'); return False,'SMTP is not configured.'
    if not to or not EMAIL_RE.match(to.strip()): log_mail(to,subject,False,'Invalid recipient address.'); return False,'Invalid recipient address.'
    sec=setting('smtp_security','auto'); sec=('ssl' if port==465 else 'starttls' if port==587 else 'none') if sec=='auto' else sec
    if _settings.get('ITSM_ENV')=='production' and (sec!='ssl' or setting('smtp_verify','1')!='1'): log_mail(to,subject,False,'Production SMTP requires verified implicit TLS'); return False,'Production SMTP requires verified implicit TLS'
    ctx=ssl.create_default_context()
    if setting('smtp_verify','1')!='1': ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    m=EmailMessage(); m['From']=formataddr((name,sender)); m['To']=to.strip(); m['Subject']=subject; m['Date']=formatdate(localtime=True); m['Message-ID']=make_msgid(domain=sender.split('@')[-1]); m['Auto-Submitted']='auto-generated'
    m.set_content(body)
    if html_body: m.add_alternative(html_body,subtype='html')
    try:
        if sec=='ssl': s=smtplib.SMTP_SSL(host,port,timeout=15,context=ctx)
        else: s=smtplib.SMTP(host,port,timeout=15)
        with s:
            if sec=='starttls': s.ehlo(); s.starttls(context=ctx); s.ehlo()
            if user: s.login(user,pwd)
            s.send_message(m)
        log_mail(to,subject,True,'Sent'); return True,'Email sent.'
    except Exception as e:
        log_mail(to,subject,False,repr(e)); return False,str(e)

PRIO_SQ={'Critical':'CRITICAL','High':'HIGH','Medium':'MEDIUM','Low':'LOW'}
def render_mail(title,intro,rows,desc,url,button):
    esc=html.escape
    text=f'{title}\n{"="*len(title)}\n\n{intro}\n\n'+'\n'.join(f'{k}: {v}' for k,v in rows if v)+(f'\n\nDescription:\n{desc}' if desc else '')+f'\n\n{button}:\n{url}\n\n--\nThis is an automated message from OpenITSM. Please do not reply to this address.'
    tr=''.join(f'<tr><td style="padding:6px 12px;color:#5b6b7b;white-space:nowrap;border-bottom:1px solid #e6edf3">{esc(str(k))}</td><td style="padding:6px 12px;border-bottom:1px solid #e6edf3"><b>{esc(str(v))}</b></td></tr>' for k,v in rows if v)
    d=f'<p style="margin:14px 0 4px;color:#5b6b7b">Description</p><div style="padding:10px 12px;background:#f4f8fb;border-left:3px solid #1477e8;white-space:pre-wrap">{esc(desc)}</div>' if desc else ''
    h=f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#17283a;max-width:640px"><div style="background:#0b2745;color:#fff;padding:14px 18px;border-radius:6px 6px 0 0"><b style="font-size:16px">OpenITSM</b> · IT Service Management</div><div style="border:1px solid #dbe6ef;border-top:0;padding:18px;border-radius:0 0 6px 6px"><h2 style="margin:0 0 8px;font-size:18px">{esc(title)}</h2><p style="margin:0 0 12px">{esc(intro)}</p><table style="border-collapse:collapse;width:100%">{tr}</table>{d}<p style="margin:20px 0"><a href="{esc(url)}" style="background:#1477e8;color:#fff;padding:10px 18px;border-radius:5px;text-decoration:none;font-weight:600">{esc(button)}</a></p><p style="color:#8696a5;font-size:12px">If the button does not open, copy this link: {esc(url)}<br>This is an automated message from OpenITSM. Please do not reply to this address.</p></div></div>'
    return text,h

def notify_actor(tid,uid,reason):
    """Notify the current assignee in-app and by email: assigned for initial assignment, turn for workflow handoff."""
    c=db(); t=c.execute('SELECT t.*,s.name service,rq.full_name requester FROM tickets t LEFT JOIN services s ON s.id=t.service_id LEFT JOIN users rq ON rq.id=t.requester_id WHERE t.id=?',(tid,)).fetchone(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    steps=c.execute('SELECT st.*,x.full_name FROM ticket_steps st LEFT JOIN users x ON x.id=st.user_id WHERE st.ticket_id=? ORDER BY st.seq',(tid,)).fetchall(); c.close()
    if not t or not u: return
    url=f'{base_url()}/tickets/{tid}'; link=f'/tickets/{tid}'; me=next((x for x in steps if x['user_id']==uid and x['status']=='Active'),None)
    prio=PRIO_SQ.get(t['priority'],t['priority']); first=(reason=='assigned')
    notify(uid,(f'New ticket – {t["code"]}' if first else f'Your turn to act – {t["code"]}'),f'{t["title"]}: {(t["description"] or "")[:300]}',link,'ticket' if first else 'step')
    if not u['email']: return
    rows=[('Ticket',t['code']),('Title',t['title']),('Type',t['type']),('Prioriteti',prio),('Service',t['service']),('Structure',t['structure']),('Created by',t['requester']),('Due date (SLA)',t['due_at'])]
    if len(steps)>1 and me: rows.append(('Workflow step',f'{me["seq"]} of {len(steps)}'))
    if me and me['instruction']: rows.append(('Required action',me['instruction']))
    done=[x for x in steps if x['status']=='Done']
    if done: rows.append(('Previous steps',' → '.join(f'{x["full_name"]} ({(x["signed_at"] or "")[:16]})' for x in done)))
    if done and done[-1]['note']: rows.append(('Last step note',done[-1]['note'][:300]))
    nxt=[x for x in steps if x['status']=='Pending']
    if nxt: rows.append(('Next step',nxt[0]['full_name']))
    title=('You have been assigned a new ticket' if first else 'Ticket awaiting your action')
    subj=f'[OpenITSM] [{prio}] {t["code"]} – '+('New ticket for you: ' if first else 'Your turn to act: ')+t['title']
    txt,h=render_mail(title,f'Hello {u["full_name"]}, '+('this ticket has been assigned to you.' if first else 'this ticket has been passed to you for action.'),rows,(t['description'] or '')[:1500],url,'Open ticket')
    send_async(u['email'],subj,txt,h)
def notify_closed(tid,actor_id,note=''):
    """Notify all ticket participants in-app and by email when a ticket closes."""
    c=db(); t=c.execute('SELECT t.*,s.name service FROM tickets t LEFT JOIN services s ON s.id=t.service_id WHERE t.id=?',(tid,)).fetchone()
    if not t: c.close(); return
    ids={t[k] for k in ('requester_id','created_by','assignee_id') if t[k]}
    ids|={r[0] for r in c.execute('SELECT user_id FROM ticket_steps WHERE ticket_id=?',(tid,)) if r[0]}
    ids|={r[0] for r in c.execute('SELECT x.user_id FROM task_assignees x JOIN tasks ta ON ta.id=x.task_id WHERE ta.ticket_id=?',(tid,))}
    users=c.execute(f"SELECT * FROM users WHERE active=1 AND id IN ({','.join('?'*len(ids))})",list(ids)).fetchall() if ids else []
    steps=c.execute('SELECT st.*,x.full_name FROM ticket_steps st LEFT JOIN users x ON x.id=st.user_id WHERE st.ticket_id=? ORDER BY st.seq',(tid,)).fetchall()
    closer=c.execute('SELECT full_name FROM users WHERE id=?',(actor_id,)).fetchone(); c.close()
    closer=closer['full_name'] if closer else '-'; url=f'{base_url()}/tickets/{tid}'; link=f'/tickets/{tid}'; prio=PRIO_SQ.get(t['priority'],t['priority'])
    rows=[('Ticket',t['code']),('Title',t['title']),('Prioriteti',prio),('Service',t['service']),('Closed by',closer),('Closed at',(t['closed_at'] or '')[:16])]
    if steps: rows.append(('Workflow chain',' → '.join(f"{x['full_name']}"+(' ✔' if x['status']=='Done' else '') for x in steps)))
    if note: rows.append(('Completion notes',note[:500]))
    for u in users:
        if u['id']==actor_id: continue
        notify(u['id'],f'Ticket closed – {t["code"]}',f'{t["title"]} was closed by {closer}',link,'ticket')
        if u['email']:
            txt,h=render_mail('Ticket closed',f'Hello {u["full_name"]}, this ticket, in which you participated, has been closed.',rows,'',url,'Open ticket')
            send_async(u['email'],f'[OpenITSM] {t["code"]} – Ticket closed: {t["title"]}',txt,h)

def notify_ticket_assignment(tid):
    c=db(); t=c.execute('SELECT assignee_id FROM tickets WHERE id=?',(tid,)).fetchone(); c.close()
    if t and t['assignee_id']: notify_actor(tid,t['assignee_id'],'assigned')

def notify_task(taskid):
    c=db(); t=c.execute('SELECT ta.*,t.code,t.title ticket_title,t.priority ticket_priority,g.name group_name FROM tasks ta JOIN tickets t ON t.id=ta.ticket_id LEFT JOIN support_groups g ON g.id=ta.group_id WHERE ta.id=?',(taskid,)).fetchone(); us=c.execute('SELECT u.* FROM users u JOIN task_assignees x ON x.user_id=u.id WHERE x.task_id=?',(taskid,)).fetchall(); c.close()
    if not t: return
    url=f'{base_url()}/tickets/{t["ticket_id"]}'; prio=PRIO_SQ.get(t['ticket_priority'],t['ticket_priority'])
    for u in us:
        notify(u['id'],f'New task – {t["title"]}',f'{t["code"]}: {t["description"] or ""}',f'/tickets/{t["ticket_id"]}','task')
        if u['email']:
            rows=[('Ticket',f'{t["code"]} – {t["ticket_title"]}'),('Tasks',t['title']),('Sektori/Grupi',t['group_name']),('Prioriteti',PRIO_SQ.get(t['priority'],t['priority'])),('Due date',(t['due_at'] or '').replace('T',' '))]
            txt,h=render_mail('You have been assigned a new task',f'Hello {u["full_name"]}, a task has been assigned to you.',rows,(t['description'] or '')[:1500],url,'Open ticket')
            send_async(u['email'],f'[OpenITSM] [{prio}] {t["code"]} – New task: {t["title"]}',txt,h)

def backup_once():
 if not os.path.exists(DB): return
 stamp=datetime.now().strftime('%Y-%m-%d'); dest=os.path.join(BACKUPS,f'itsm-{stamp}.db')
 if not os.path.exists(dest):
  src=sqlite3.connect(DB); dst=sqlite3.connect(dest); src.backup(dst); dst.close(); src.close()
 cutoff=datetime.now()-timedelta(days=30)
 for f in os.listdir(BACKUPS):
  p=os.path.join(BACKUPS,f)
  if f.endswith('.db') and datetime.fromtimestamp(os.path.getmtime(p))<cutoff: os.remove(p)
def backup_worker():
 while True:
  try: backup_once()
  except Exception as e: print('Backup error:',e)
  time.sleep(3600)

@app.context_processor
def ctx():
 if 'uid' not in session:return {}
 uid=session['uid']; c=db(); n=c.execute('SELECT count(*) n FROM notifications WHERE user_id=? AND is_read=0',(uid,)).fetchone()['n']; a=c.execute('SELECT * FROM announcements WHERE active=1 ORDER BY id DESC LIMIT 3').fetchall(); last=c.execute('SELECT COALESCE(MAX(id),0) m FROM notifications WHERE user_id=?',(uid,)).fetchone()['m']; popup=None
 if session.pop('popup',None):
  vs,va=ticket_scope_sql(current(),ORG,c); tk=c.execute("SELECT t.id,t.code,t.title,t.priority,t.due_at FROM tickets t WHERE t.assignee_id=? AND "+vs+" AND t.status NOT IN ('Resolved','Closed') ORDER BY t.id DESC LIMIT 10",[uid,*va]).fetchall()
  ts=c.execute("SELECT ta.title,ta.due_at,ta.ticket_id,t.code FROM tasks ta JOIN task_assignees x ON x.task_id=ta.id JOIN tickets t ON t.id=ta.ticket_id WHERE x.user_id=? AND "+vs+" AND ta.status!='Completed' ORDER BY ta.id DESC LIMIT 10",[uid,*va]).fetchall()
  if tk or ts: popup={'tickets':tk,'tasks':ts,'count':len(tk)+len(ts)}
 c.close(); return {'unread_notifications':n,'active_announcements':a,'last_notif_id':last,'login_popup':popup}

DUMMY_PASSWORD_HASH=generate_password_hash(secrets.token_urlsafe(32))



import unicodedata as _ud








# ---------------- Reports + eksport ----------------






MANAGERS=('System Administrator','Central Administrator')
def send_bulk(items):
    def run():
        for to,s,b in items:
            try: send_email(to,s,b)
            except Exception as e: print('Email failed for',to,e)
    if items:
        _database.dispatch_after_commit(run)



# ---------------- Direktoria, Profili, Poll ----------------



# ===================== v8.5.2: tasks with timelines, subtasks and audit log =====================






TASK_ICONS={'Created':'＋','Assigned':'➜','Started':'▶','Update':'✎','Subtask':'⊕','Completed':'✔','Reopened':'↺'}



# ---------------- Audit log (System Administrator + Central Administrator) ----------------
AUDIT_ROLES=('System Administrator','Central Administrator')


# ---------------- HTTPS (automatically generated self-signed certificate) ----------------
CERT_DIR=os.path.join(BASE,'certs')
def local_ips():
    ips={'127.0.0.1'}
    try:
        for ai in socket.getaddrinfo(socket.gethostname(),None): ips.add(ai[4][0])
    except OSError: pass
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('10.255.255.255',1)); ips.add(s.getsockname()[0]); s.close()
    except OSError: pass
    return sorted(i for i in ips if not i.startswith('169.254') and '%' not in i and not i.lower().startswith('fe80'))
def ensure_cert():
    cp,kp=_settings.get('ITSM_CERT'),_settings.get('ITSM_KEY')
    if cp and kp and os.path.exists(cp) and os.path.exists(kp): return cp,kp
    os.makedirs(CERT_DIR,exist_ok=True); cert=os.path.join(CERT_DIR,'itsm-cert.pem'); key=os.path.join(CERT_DIR,'itsm-key.pem'); sanf=os.path.join(CERT_DIR,'san.txt')
    extra=[x.strip() for x in _settings.get('ITSM_CERT_HOSTS','').split(',') if x.strip()]
    names=sorted(set(['localhost',socket.gethostname(),'::1']+extra+local_ips())); sig=','.join(names)
    if os.path.exists(cert) and os.path.exists(key) and os.path.exists(sanf) and open(sanf).read()==sig: return cert,key
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k=rsa.generate_private_key(public_exponent=65537,key_size=2048); sub=x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME,'OpenITSM'),x509.NameAttribute(NameOID.COMMON_NAME,'OpenITSM')])
    san=[]
    for n in names:
        try: san.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError: san.append(x509.DNSName(n))
    nb=datetime.now(timezone.utc)-timedelta(days=1)
    crt=(x509.CertificateBuilder().subject_name(sub).issuer_name(sub).public_key(k.public_key()).serial_number(x509.random_serial_number()).not_valid_before(nb).not_valid_after(nb+timedelta(days=825))
         .add_extension(x509.SubjectAlternativeName(san),critical=False).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
         .add_extension(x509.KeyUsage(digital_signature=True,key_encipherment=True,content_commitment=False,data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=False,decipher_only=False),critical=True)
         .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(k,hashes.SHA256()))
    with open(key,'wb') as f: f.write(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
    try: os.chmod(key,0o600)
    except OSError: pass
    with open(cert,'wb') as f: f.write(crt.public_bytes(serialization.Encoding.PEM))
    open(sanf,'w').write(sig); print('OpenITSM: generated a new HTTPS certificate for:',sig); return cert,key
def start_http_redirect(host,port,https_port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    hre=re.compile(r'^(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.\-]+)(:\d+)?$')
    class H(BaseHTTPRequestHandler):
        def _r(self):
            m=hre.match(self.headers.get('Host','') or ''); h=m.group(1) if m else 'localhost'
            self.send_response(308); self.send_header('Location',f'https://{h}:{https_port}{self.path if self.path.startswith("/") else "/"}'); self.send_header('Content-Length','0'); self.end_headers()
        do_GET=do_HEAD=do_POST=do_PUT=do_DELETE=_r
        def log_message(self,*a): pass
    try:
        srv=ThreadingHTTPServer((host,port),H); threading.Thread(target=srv.serve_forever,daemon=True).start(); return True
    except OSError as e: print(f'WARNING: HTTP to HTTPS redirection on port {port} did not start ({e}).'); return False
def run_server():
    tls=_settings.get('ITSM_TLS','1')!='0'; host=_settings.get('ITSM_HOST','0.0.0.0' if tls else '127.0.0.1'); http_port=int(_settings.get('PORT','5000'))
    if not tls:
        print('WARNING: ITSM_TLS=0 serves unencrypted HTTP. Use for local development only.')
        try: from waitress import serve
        except ImportError: return app.run(host=host,port=http_port,debug=False)
        return serve(app,host=host,port=http_port,threads=int(_settings.get('ITSM_THREADS','8')))
    https_port=int(_settings.get('ITSM_HTTPS_PORT','5443')); cert,key=ensure_cert(); app.config['SESSION_COOKIE_SECURE']=True
    if _settings.get('ITSM_DEBUG')=='1': return app.run(host=host,port=https_port,debug=True,ssl_context=(cert,key))
    redirect_on=_settings.get('ITSM_HTTP_REDIRECT','1')=='1' and start_http_redirect(host,http_port,https_port)
    print('\n=== OpenITSM HTTPS server ==='); print(f'   https://localhost:{https_port}')
    for ip in local_ips():
        if ip!='127.0.0.1' and ':' not in ip: print(f'   https://{ip}:{https_port}')
    if redirect_on: print(f'   (HTTP port {http_port} redirects to HTTPS)')
    print(f'   Certificate: {cert}\n   Your browser may warn about a self-signed certificate. See README.md.\n')
    try:
        from cheroot.wsgi import Server
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        srv=Server((host,https_port),app,numthreads=16,timeout=30); srv.ssl_adapter=BuiltinSSLAdapter(cert,key)
        try: srv.ssl_adapter.context.minimum_version=ssl.TLSVersion.TLSv1_2
        except Exception: pass
        try: srv.start()
        except KeyboardInterrupt: srv.stop()
        return
    except ImportError: print('WARNING: cheroot not installed; using Werkzeug TLS server.')
    from werkzeug.serving import make_server
    make_server(host,https_port,app,threaded=True,ssl_context=(cert,key)).serve_forever()
from handler_registry import register_family as _register_family, register_core_routes as _register_core_routes
_register_family(_runtime,'read')
_register_family(_runtime,'tickets')
_register_family(_runtime,'infrastructure')
_register_family(_runtime,'identity')
_register_core_routes(app,globals())
_register_family(_runtime,'organization')
_register_family(_runtime,'collaboration')
