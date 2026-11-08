"""Organization hierarchy and ticket visibility.
Regjimi 'legacy' = sjellja e vjetër sipas roleve; 'org' = dukshmëri sipas njësisë/sektorit. Ndërrohet nga faqja /org."""
import re
from flask import abort, g, render_template, request, redirect, url_for, flash
SCHEMA="CREATE TABLE IF NOT EXISTS org_units(id INTEGER PRIMARY KEY,parent_id INTEGER,name TEXT NOT NULL,kind TEXT DEFAULT 'SECTOR',sort INTEGER DEFAULT 0);"
ORG_GLOBAL_ROLES=('Management','Auditor')      # shohin dhe auditojnë gjithçka (drejtuesit)
ORG_ADMIN_ROLES=('System Administrator','Central Administrator')
TREE=('Example Organization','ORG',[
 ('IT Operations','UNIT',['Service Desk','Network Operations','Systems Administration']),
 ('Security Operations','UNIT',['Monitoring','Incident Response'])])
SVC_MAP={}
def init(app,D):
    db,login_required,current,audit,setting,GLOBAL,AUDIT_ROLES=D['db'],D['login_required'],D['current'],D['audit'],D['setting'],D['GLOBAL'],D['AUDIT_ROLES']
    def cache(k,f):
        if not hasattr(g,'_org'): g._org={}
        if k not in g._org: g._org[k]=f()
        return g._org[k]
    def mode(): return cache('mode',lambda: setting('visibility_mode','legacy'))
    def org_mode(): return mode()=='org'
    def root_id(c): r=c.execute('SELECT id FROM org_units WHERE parent_id IS NULL ORDER BY id LIMIT 1').fetchone(); return r['id'] if r else None
    def subtree(c,uid): return [r[0] for r in c.execute('WITH RECURSIVE s(id) AS (SELECT ? UNION SELECT o.id FROM org_units o JOIN s ON o.parent_id=s.id) SELECT id FROM s',(uid,))]
    def scope_ids(c,u):
        def f():
            if not u['org_unit_id']: return []
            return subtree(c,u['org_unit_id']) if u['org_head'] else [u['org_unit_id']]
        return cache(('sc',u['id']),f)
    def is_global(c,u): return u['role']=='System Administrator'
    def involved(a): return (f"({a}.requester_id=? OR {a}.assignee_id=? OR {a}.created_by=? OR EXISTS(SELECT 1 FROM tasks ta0 JOIN task_assignees x0 ON x0.task_id=ta0.id WHERE ta0.ticket_id={a}.id AND x0.user_id=?) OR EXISTS(SELECT 1 FROM ticket_steps st0 WHERE st0.ticket_id={a}.id AND st0.user_id=?)",[0]*0)
    def vis_sql(u,a='t'):
        c=db()
        try:
            if is_global(c,u): return '1=1',[]
            ids=scope_ids(c,u)
        finally: c.close()
        s=involved(a)[0]; args=[u['id']]*5
        if ids: s+=f" OR {a}.unit_id IN ({','.join('?'*len(ids))})"; args+=ids
        s+=")"
        return s,args
    def can_view(c,u,t):
        if is_global(c,u) or u['id'] in (t['requester_id'],t['assignee_id'],t['created_by']): return True
        if c.execute('SELECT 1 FROM tasks ta JOIN task_assignees x ON x.task_id=ta.id WHERE ta.ticket_id=? AND x.user_id=?',(t['id'],u['id'])).fetchone(): return True
        if c.execute('SELECT 1 FROM ticket_steps WHERE ticket_id=? AND user_id=?',(t['id'],u['id'])).fetchone(): return True
        if t['unit_id'] and t['unit_id'] in scope_ids(c,u): return True
        return False  # Org mode uses explicit unit scope; legacy structure must not bypass it.
    def user_filter(c,u):
        """Kushti për listën e përdoruesve në Ngarkesa: vetja + ata të njësisë/sektorit; None = të gjithë."""
        if is_global(c,u): return None
        ids=scope_ids(c,u); s="(u.id=:uid"+(f" OR u.org_unit_id IN ({','.join(str(int(i)) for i in ids)})" if ids else '')+")"
        return s,{'uid':u['id']}
    def leader(c,u): return u['role'] in ORG_GLOBAL_ROLES or bool(u['org_head'] and u['org_unit_id'] and u['org_unit_id']==root_id(c))
    def can_audit(u): return u['role'] in ('System Administrator','Central Administrator','Management','Auditor')
    def can_view_team(c,u,owner_id):
        if is_global(c,u): return True
        if (u['org_head'] or u['role'] in ('Management','Auditor')) and u['org_unit_id']:
            o=c.execute('SELECT org_unit_id FROM users WHERE id=?',(owner_id,)).fetchone()
            return bool(o and o['org_unit_id'] in scope_ids(c,u))
        return False
    def options(c):
        rows=c.execute('SELECT * FROM org_units ORDER BY sort,id').fetchall(); by={}; 
        for r in rows: by.setdefault(r['parent_id'],[]).append(r)
        out=[]
        def walk(pid,path):
            for r in by.get(pid,[]): p=path+[r['name']]; out.append(dict(id=r['id'],name=r['name'],kind=r['kind'],label=' › '.join(p),depth=len(path))); walk(r['id'],p)
        walk(None,[]); return out
    def route(c,tid,unit_id,service_id):
        uid=None
        if str(unit_id or '').isdigit() and c.execute('SELECT 1 FROM org_units WHERE id=?',(int(unit_id),)).fetchone(): uid=int(unit_id)
        if not uid and str(service_id or '').isdigit():
            s=c.execute('SELECT unit_id FROM services WHERE id=?',(int(service_id),)).fetchone(); uid=s['unit_id'] if s else None
        if not uid: uid=int(setting('intake_unit_id','0') or 0) or None
        c.execute('UPDATE tickets SET unit_id=? WHERE id=?',(uid,tid))
    def backfill(c):
        n=0; intake=int(setting('intake_unit_id','0') or 0) or None
        for t in c.execute('SELECT id,service_id FROM tickets WHERE unit_id IS NULL').fetchall(): route(c,t['id'],None,t['service_id']); n+=1
        return n
    def unit_name(uid):
        if not uid: return ''
        c=db(); r=c.execute('SELECT name FROM org_units WHERE id=?',(uid,)).fetchone(); c.close(); return r['name'] if r else ''
    app.jinja_env.globals['unit_name']=unit_name
    def _cu():
        try: return current()
        except Exception: return None
    app.jinja_env.globals['can_audit_u']=lambda: bool(_cu() and can_audit(_cu()))
    def _org_nav():
        u=_cu()
        if not u: return False
        if u['role'] in ORG_ADMIN_ROLES: return True
        c=db()
        try: return leader(c,u)
        finally: c.close()
    app.jinja_env.globals['org_nav']=_org_nav
    @app.route('/org',methods=['GET','POST'])
    @login_required
    def org_page():
        u=current(); c=db()
        if u['role'] not in ORG_ADMIN_ROLES and not leader(c,u): c.close(); audit('AccessDenied','Org',0); return 'Access Denied',403
        edit=u['role'] in ORG_ADMIN_ROLES; f=request.form
        if request.method=='POST':
            if not edit: c.close(); return 'Access Denied',403
            a=f.get('action'); msg=None
            def uid_(k): return int(f[k]) if (f.get(k) or '').isdigit() else None
            if a not in ('unit_add','unit_rename','unit_move','unit_delete','assign_users','service_map','settings'): c.close(); abort(400)
            for key in request.form:
                if key.startswith(('unit_','head_','svc_')) and len(f.getlist(key))>1: c.close(); abort(400)
            for key in (('id',) if a in ('unit_rename','unit_move','unit_delete') else ()):
                if not uid_(key) or not c.execute('SELECT 1 FROM org_units WHERE id=?',(uid_(key),)).fetchone(): c.close(); abort(400)
            for key in (('parent_id',) if a in ('unit_add','unit_move') else ('intake_unit_id',) if a=='settings' else ()):
                if f.get(key) and (not uid_(key) or not c.execute('SELECT 1 FROM org_units WHERE id=?',(uid_(key),)).fetchone()): c.close(); abort(400)
            if a in ('assign_users','service_map'):
                prefix='unit_' if a=='assign_users' else 'svc_'; table='users' if a=='assign_users' else 'services'
                for key in f:
                    if not key.startswith(prefix): continue
                    raw_id=key[len(prefix):]; raw_unit=f[key]
                    if not raw_id.isascii() or not raw_id.isdigit() or not c.execute('SELECT 1 FROM '+table+' WHERE id=?',(int(raw_id),)).fetchone(): c.close(); abort(400)
                    if raw_unit and (not raw_unit.isascii() or not raw_unit.isdigit() or not c.execute('SELECT 1 FROM org_units WHERE id=?',(int(raw_unit),)).fetchone()): c.close(); abort(400)
            # Central administrators manage their assigned scope, never global policy.
            scoped = u['role'] == 'Central Administrator'
            allowed_units = scope_ids(c,u) if scoped else None
            if scoped:
                target = uid_('id')
                parent = uid_('parent_id')
                denied = a == 'settings'
                if a == 'unit_add': denied = parent not in allowed_units
                if a in ('unit_rename','unit_delete','unit_move'): denied = target not in allowed_units
                if a == 'unit_move': denied = denied or parent not in allowed_units
                if denied: c.close(); audit('AccessDenied','Org',target or 0); return 'Access Denied',403
            if a=='unit_add' and f.get('name','').strip():
                p=uid_('parent_id'); kind=('STRUCT' if p is None else (f.get('kind') if f.get('kind') in ('UNIT','SECTOR') else 'SECTOR'))
                c.execute('INSERT INTO org_units(parent_id,name,kind,sort) VALUES(?,?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM org_units WHERE parent_id IS ?))',(p,f['name'].strip()[:120],kind,p)); msg='Struktura e pavarur u shtua.' if p is None else 'Njësia u shtua.'
            elif a=='unit_rename' and uid_('id') and f.get('name','').strip(): c.execute('UPDATE org_units SET name=? WHERE id=?',(f['name'].strip()[:120],uid_('id'))); msg='Emri u ndryshua.'
            elif a=='unit_move' and uid_('id'):
                i,p=uid_('id'),uid_('parent_id')
                if p and (p==i or p in subtree(c,i)): msg='Nuk mund ta zhvendosni brenda vetes.'
                elif p is None and i==root_id(c): msg='Rrënja kryesore nuk zhvendoset.'
                elif p is None: c.execute("UPDATE org_units SET parent_id=NULL,kind='STRUCT' WHERE id=?",(i,)); msg='U bë strukturë e pavarur.'
                else: c.execute('UPDATE org_units SET parent_id=? WHERE id=?',(p,i)); msg='Njësia u zhvendos.'
            elif a=='unit_delete' and uid_('id') and f.get('confirm'):
                i=uid_('id'); busy=c.execute('SELECT (SELECT count(*) FROM org_units WHERE parent_id=?1)+(SELECT count(*) FROM users WHERE org_unit_id=?1)+(SELECT count(*) FROM tickets WHERE unit_id=?1)+(SELECT count(*) FROM services WHERE unit_id=?1) n',(i,)).fetchone()['n']
                if busy: msg='Njësia nuk është bosh (ka nënnjësi, përdorues, ticket-e ose shërbime).'
                elif i==root_id(c): msg='The root organization cannot be deleted.'
                else: c.execute('DELETE FROM org_units WHERE id=?',(i,)); msg='Njësia u fshi.'
            elif a=='assign_users':
                for r in c.execute("SELECT id,org_unit_id,org_head,role FROM users WHERE active=1").fetchall():
                    if f"unit_{r['id']}" not in f and f"head_{r['id']}" not in f: continue
                    if scoped and (r['org_unit_id'] not in allowed_units or r['role']=='System Administrator'): continue
                    un=f.get(f"unit_{r['id']}") if f"unit_{r['id']}" in f else r['org_unit_id']; un=int(un) if str(un or '').isdigit() else None
                    if scoped and un not in allowed_units: c.rollback(); c.close(); return 'Access Denied',403
                    if scoped and f.get(f"head_{r['id']}") and (not u['org_head'] or un and not set(subtree(c,un)).issubset(allowed_units)): c.rollback(); c.close(); abort(403)
                    c.execute('UPDATE users SET org_unit_id=?,org_head=? WHERE id=?',(un,1 if f.get(f"head_{r['id']}") and un else 0,r['id']))
                msg='Caktimet e përdoruesve u ruajtën.'
            elif a=='service_map':
                for r in c.execute('SELECT id,unit_id FROM services').fetchall():
                    if f"svc_{r['id']}" not in f: continue
                    if scoped and r['unit_id'] not in allowed_units: continue
                    un=f.get(f"svc_{r['id']}"); un=int(un) if un and un.isdigit() else None
                    if scoped and un not in allowed_units: c.rollback(); c.close(); return 'Access Denied',403
                    c.execute('UPDATE services SET unit_id=? WHERE id=?',(un,r['id']))
                msg='Lidhja shërbim → sektor u ruajt.'
            elif a=='settings':
                newm=f.get('mode') if f.get('mode') in ('legacy','org') else 'legacy'; intake=uid_('intake_unit_id')
                if intake: c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('intake_unit_id',?)",(str(intake),))
                if newm=='org' and mode()!='org' and not f.get('confirm'): msg='Për të kaluar te dukshmëria sipas strukturës, konfirmoni kutinë.'
                else:
                    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('visibility_mode',?)",(newm,)); g._org={}
                    if newm=='org': c.commit(); nb=backfill(c); msg=f'Dukshmëria sipas strukturës u aktivizua; {nb} ticket-e pa njësi u drejtuan automatikisht.'
                    else: msg='U kthye dukshmëria e vjetër sipas roleve.'
            if msg: c.commit(); c.close(); audit('Update','Org',0,new=a); flash(msg,'success' if 'Nuk' not in msg and 'konfirmoni' not in msg else 'danger'); return redirect(url_for('org_page'))
        opts=options(c); counts={r['id']:r for r in c.execute("SELECT o.id,(SELECT count(*) FROM users u WHERE u.org_unit_id=o.id AND u.active=1) nu,(SELECT count(*) FROM tickets t WHERE t.unit_id=o.id AND t.status NOT IN ('Resolved','Closed')) nt FROM org_units o")}
        heads={}
        for r in c.execute('SELECT org_unit_id,full_name FROM users WHERE org_head=1 AND active=1'): heads.setdefault(r['org_unit_id'],[]).append(r['full_name'])
        users=c.execute("SELECT id,full_name,role,org_unit_id,org_head,structure FROM users WHERE active=1 ORDER BY full_name").fetchall()
        services=c.execute('SELECT id,name,unit_id FROM services WHERE is_main=1 ORDER BY name').fetchall() if 'is_main' in [r['name'] for r in c.execute('PRAGMA table_info(services)')] else c.execute('SELECT id,name,unit_id FROM services ORDER BY name').fetchall()
        nounit=c.execute("SELECT count(*) n FROM users WHERE active=1 AND role NOT IN ('Requester','Local Administrator','Management','Auditor') AND org_unit_id IS NULL").fetchone()['n']
        nt0=c.execute('SELECT count(*) n FROM tickets WHERE unit_id IS NULL').fetchone()['n']; m=mode(); intake=int(setting('intake_unit_id','0') or 0); c.close()
        if u['role']!='System Administrator':
            c=db(); ids=scope_ids(c,u); c.close()
            opts=[o for o in opts if o['id'] in ids]
            counts={k:v for k,v in counts.items() if k in ids}; heads={k:v for k,v in heads.items() if k in ids}
            users=[r for r in users if r['org_unit_id'] in ids]; services=[r for r in services if r['unit_id'] in ids]
            nounit=0; nt0=0
        return render_template('org.html',opts=opts,counts=counts,heads=heads,users=users,services=services,nounit=nounit,nt0=nt0,mode=m,intake=intake,edit=edit,global_roles=ORG_GLOBAL_ROLES)
    return type('ORG',(),dict(org_mode=staticmethod(org_mode),is_global=staticmethod(is_global),vis_sql=staticmethod(vis_sql),can_view=staticmethod(can_view),user_filter=staticmethod(user_filter),can_audit=staticmethod(can_audit),can_view_team=staticmethod(can_view_team),options=staticmethod(options),route=staticmethod(route),scope_ids=staticmethod(scope_ids)))
