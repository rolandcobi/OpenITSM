"""Hapësira ime: ekipe (Teams), borde Trello-style, detyra personale dhe të sektorit, dashboard performance."""
import re
from authorization import directory_scope_sql
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY,name TEXT NOT NULL,description TEXT,color TEXT DEFAULT '#2f7cf6',owner_id INTEGER,created_at TEXT);
CREATE TABLE IF NOT EXISTS team_members(team_id INTEGER,user_id INTEGER,role TEXT DEFAULT 'Member',added_at TEXT,PRIMARY KEY(team_id,user_id));
CREATE TABLE IF NOT EXISTS boards(id INTEGER PRIMARY KEY,team_id INTEGER,name TEXT NOT NULL,owner_id INTEGER,created_at TEXT,archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS board_lists(id INTEGER PRIMARY KEY,board_id INTEGER,name TEXT,pos INTEGER DEFAULT 0,is_done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY,board_id INTEGER,list_id INTEGER,title TEXT NOT NULL,description TEXT,assignee_id INTEGER,creator_id INTEGER,priority TEXT DEFAULT 'Medium',due_at TEXT,created_at TEXT,completed_at TEXT,pos INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_cards_b ON cards(board_id,list_id);CREATE INDEX IF NOT EXISTS ix_cards_a ON cards(assignee_id);CREATE INDEX IF NOT EXISTS ix_boards_t ON boards(team_id);"""
SPACE_ADMIN = ('System Administrator', 'Central Administrator', 'Service Desk Manager', 'Management')
SOURCES = ('Personal Initiative', 'Request', 'Monthly Plan', 'Assigned Task', 'Other'); PRIOS = ('Low', 'Medium', 'High', 'Critical'); DEFAULT_LISTS = (('To Do', 0), ('In Progress', 0), ('In Review', 0), ('Completed', 1))
def init(app, D):
    db, login_required, current, audit, notify, now = D['db'], D['login_required'], D['current'], D['audit'], D['notify'], D['now']
    def after(c, fn, *a, **k):
        c.commit(); return fn(*a, **k)   # commit para audit/notify (ato hapin lidhje të vetën → shmang 'database is locked')
    def team_role(c, u, tid):
        t = c.execute('SELECT owner_id FROM teams WHERE id=?', (tid,)).fetchone()
        if not t: return None
        if t['owner_id'] == u['id']: return 'Lead'
        r = c.execute('SELECT role FROM team_members WHERE team_id=? AND user_id=?', (tid, u['id'])).fetchone()
        if r:
            owner=c.execute('SELECT * FROM users WHERE id=?',(t['owner_id'],)).fetchone()
            org=D.get('org')
            if u['role']=='System Administrator' or (owner and org and u['org_unit_id'] in org.scope_ids(c,owner)): return r['role']
            return None
        org = D.get('org')
        if org is not None: return 'Viewer' if org.can_view_team(c, u, t['owner_id']) else None   # dukshmëri sipas strukturës
        return 'Admin' if u['role'] in ('System Administrator', 'Central Administrator') else ('Viewer' if u['role'] in SPACE_ADMIN else None)
    def board_access(c, u, bid):
        b = c.execute('SELECT * FROM boards WHERE id=?', (bid,)).fetchone()
        if not b: return None, None
        if b['team_id'] is None: return b, ('write' if b['owner_id'] == u['id'] else None)
        r = team_role(c, u, b['team_id']); return b, ('write' if r in ('Lead', 'Admin', 'Member') else 'read' if r == 'Viewer' else None)
    def make_board(c, team_id, name, owner):
        bid = c.execute('INSERT INTO boards(team_id,name,owner_id,created_at) VALUES(?,?,?,?)', (team_id, name[:80], owner, now())).lastrowid
        for i, (n, d) in enumerate(DEFAULT_LISTS): c.execute('INSERT INTO board_lists(board_id,name,pos,is_done) VALUES(?,?,?,?)', (bid, n, i, d))
        return bid
    D['space_board_access'] = board_access
    def srcref(f):
        x = f.get('source'); return (x if x in SOURCES else SOURCES[0]), f.get('source_ref', '').strip()[:80]
    def personal_board(c, u):
        r = c.execute('SELECT id FROM boards WHERE team_id IS NULL AND owner_id=? AND archived=0 ORDER BY id LIMIT 1', (u['id'],)).fetchone()
        return r['id'] if r else make_board(c, None, 'Detyrat personale', u['id'])
    def due(s):
        s = (s or '').strip(); return s + ' 23:59:59' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) else None
    def stats(c, tid):
        rows = c.execute('SELECT k.*,l.is_done,l.name ln,u.full_name an FROM cards k JOIN boards b ON b.id=k.board_id JOIN board_lists l ON l.id=k.list_id LEFT JOIN users u ON u.id=k.assignee_id WHERE b.team_id=? AND b.archived=0', (tid,)).fetchall()
        n = now(); S = dict(src={}, total=len(rows), done=0, overdue=0, ok=0, withdue=0, cyc=[], members={}, lists={}, unassigned=0, overdue_list=[], soon=[])
        for r in rows:
            m = S['members'].setdefault(r['an'] or '—', dict(name=r['an'] or 'Pa caktuar', assigned=0, done=0, overdue=0, ok=0, withdue=0))
            S['lists'][r['ln']] = S['lists'].get(r['ln'], 0) + 1; m['assigned'] += 1; sk = r['source'] or SOURCES[0]; S['src'][sk] = S['src'].get(sk, 0) + 1
            if not r['assignee_id']: S['unassigned'] += 1
            if r['is_done']:
                S['done'] += 1; m['done'] += 1
                if r['due_at'] and r['completed_at']:
                    S['withdue'] += 1; m['withdue'] += 1
                    if r['completed_at'] <= r['due_at']: S['ok'] += 1; m['ok'] += 1
                if r['completed_at'] and r['created_at']:
                    try: S['cyc'].append((datetime.strptime(r['completed_at'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(r['created_at'], '%Y-%m-%d %H:%M:%S')).total_seconds() / 86400)
                    except ValueError: pass
            elif r['due_at']:
                if r['due_at'] < n: S['overdue'] += 1; m['overdue'] += 1; S['overdue_list'].append(r)
                elif r['due_at'] < (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'): S['soon'].append(r)
        t = S['total']; S['open'] = t - S['done']
        S['completion'] = round(100 * S['done'] / t) if t else 0
        S['ontime'] = round(100 * S['ok'] / S['withdue']) if S['withdue'] else 100
        S['overdue_pct'] = round(100 * S['overdue'] / S['open']) if S['open'] else 0
        S['score'] = round(.4 * S['completion'] + .4 * S['ontime'] + .2 * (100 - S['overdue_pct'])) if t else None
        S['avg_cycle'] = round(sum(S['cyc']) / len(S['cyc']), 1) if S['cyc'] else None
        for m in S['members'].values(): m['pct'] = round(100 * m['done'] / m['assigned']) if m['assigned'] else 0; m['ontime'] = round(100 * m['ok'] / m['withdue']) if m['withdue'] else 100
        S['member_rows'] = sorted(S['members'].values(), key=lambda m: (-m['done'], -m['assigned']))
        days = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(13, -1, -1)]
        S['trend'] = [dict(d=d[8:] + '.' + d[5:7], created=sum(1 for r in rows if (r['created_at'] or '')[:10] == d), done=sum(1 for r in rows if (r['completed_at'] or '')[:10] == d)) for d in days]
        S['tmax'] = max([1] + [max(x['created'], x['done']) for x in S['trend']]); S['lmax'] = max([1] + list(S['lists'].values()))
        return S
    def summary(c,u):
        ts=[t for t in c.execute('SELECT * FROM teams ORDER BY name').fetchall() if team_role(c,u,t['id'])]
        out = []
        for t in ts:
            s = stats(c, t['id']); out.append(dict(t=t, members=c.execute('SELECT count(*) n FROM team_members WHERE team_id=?', (t['id'],)).fetchone()['n'], **{k: s[k] for k in ('total', 'done', 'open', 'overdue', 'completion', 'ontime', 'score')}))
        return out
    D['space_summary'] = summary
    @app.route('/space', methods=['GET', 'POST'])
    @login_required
    def space():
        u = current(); c = db(); f = request.form
        if request.method == 'POST':
            a = f.get('action'); name = f.get('name', '').strip()[:80]; pr = f.get('priority') if f.get('priority') in PRIOS else 'Medium'
            back = f.get('next', ''); back = back if back.startswith('/space') else url_for('space')
            if a == 'task_add':
                title = f.get('title', '').strip()[:200]; asg = u['id']
                if not title: c.close(); flash('Shkruani çfarë duhet bërë.', 'danger'); return redirect(back)
                if (f.get('dest') or 'me').startswith('t:'):
                    try: _, ts_, us_ = f['dest'].split(':'); tid, uid = int(ts_), int(us_)
                    except ValueError: c.close(); return 'Kërkesë e pavlefshme', 400
                    if team_role(c, u, tid) not in ('Lead', 'Admin', 'Member'): c.close(); audit('AccessDenied', 'Team', tid); return 'Access Denied', 403
                    asg = uid if uid and c.execute('SELECT 1 FROM team_members WHERE team_id=? AND user_id=?', (tid, uid)).fetchone() else None
                    r = c.execute('SELECT id FROM boards WHERE team_id=? AND archived=0 ORDER BY id LIMIT 1', (tid,)).fetchone(); bid = r['id'] if r else make_board(c, tid, 'Detyrat e ekipit', u['id'])
                else: bid = personal_board(c, u)
                l = c.execute('SELECT id FROM board_lists WHERE board_id=? ORDER BY pos,id LIMIT 1', (bid,)).fetchone()
                c.execute('INSERT INTO cards(board_id,list_id,title,description,assignee_id,creator_id,priority,due_at,created_at,pos,source,source_ref) VALUES(?,?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(pos),0)+1 FROM cards WHERE list_id=?),?,?)', (bid, l['id'], title, f.get('description', '')[:2000], asg, u['id'], pr, due(f.get('due')), now(), l['id'], *srcref(f)))
                if asg and asg != u['id']: after(c, notify, asg, 'Detyrë e re nga ' + u['full_name'], title[:120], url_for('space_board', bid=bid))
                c.commit(); c.close(); flash('Detyra u shtua.', 'success'); return redirect(back)
            if a == 'task_done':
                k = c.execute('SELECT * FROM cards WHERE id=?', (int(f['card_id']) if (f.get('card_id') or '').isdigit() else 0,)).fetchone()
                if not k or board_access(c, u, k['board_id'])[1] != 'write': c.close(); audit('AccessDenied', 'Card', k['id'] if k else 0); return 'Access Denied', 403
                dl = c.execute('SELECT id FROM board_lists WHERE board_id=? AND is_done=1 ORDER BY pos LIMIT 1', (k['board_id'],)).fetchone()
                if dl: c.execute('UPDATE cards SET list_id=?,completed_at=COALESCE(completed_at,?) WHERE id=?', (dl['id'], now(), k['id'])); c.commit()
                c.close(); return redirect(back)
            if not name: c.close(); flash('Emri është i detyrueshëm.', 'danger'); return redirect(url_for('space'))
            if a == 'team_create':
                col = f.get('color', ''); col = col if re.fullmatch(r'#[0-9a-fA-F]{6}', col) else '#2f7cf6'
                tid = c.execute('INSERT INTO teams(name,description,color,owner_id,created_at) VALUES(?,?,?,?,?)', (name, f.get('description', '')[:300], col, u['id'], now())).lastrowid
                c.execute("INSERT INTO team_members(team_id,user_id,role,added_at) VALUES(?,?, 'Lead',?)", (tid, u['id'], now())); make_board(c, tid, 'Detyrat e ekipit', u['id']); c.commit(); c.close(); audit('Create', 'Team', tid, new=name); return redirect(url_for('space_team', tid=tid))
            if a == 'board_create':
                bid = make_board(c, None, name, u['id']); c.commit(); c.close(); return redirect(url_for('space_board', bid=bid))
        today = now()[:10]; src = request.args.get('src', ''); src = src if src in SOURCES else ''
        cards = c.execute('SELECT k.*,b.name bn,t.name tn,t.color tc FROM cards k JOIN boards b ON b.id=k.board_id JOIN board_lists l ON l.id=k.list_id LEFT JOIN teams t ON t.id=b.team_id WHERE k.assignee_id=? AND l.is_done=0 AND b.archived=0' + (' AND k.source=?' if src else '') + ' ORDER BY k.due_at IS NULL,k.due_at LIMIT 100', (u['id'],) + ((src,) if src else ())).fetchall()
        donec = c.execute('SELECT k.title,k.completed_at,k.board_id FROM cards k JOIN board_lists l ON l.id=k.list_id WHERE k.assignee_id=? AND l.is_done=1 ORDER BY k.completed_at DESC LIMIT 5', (u['id'],)).fetchall()
        teams = c.execute('SELECT t.*,(SELECT count(*) FROM team_members m WHERE m.team_id=t.id) mc FROM teams t WHERE t.owner_id=?1 OR EXISTS(SELECT 1 FROM team_members m WHERE m.team_id=t.id AND m.user_id=?1) ORDER BY t.name', (u['id'],)).fetchall()
        personal = c.execute('SELECT b.*,(SELECT count(*) FROM cards k WHERE k.board_id=b.id) n FROM boards b WHERE b.team_id IS NULL AND b.owner_id=? AND b.archived=0', (u['id'],)).fetchall()
        cards=[k for k in cards if board_access(c,u,k['board_id'])[1]]
        donec=[k for k in donec if board_access(c,u,k['board_id'])[1]]
        teams=[t for t in teams if team_role(c,u,t['id'])]
        topt = [dict(id=t['id'], name=t['name'], members=c.execute('SELECT u.id,u.full_name FROM team_members m JOIN users u ON u.id=m.user_id WHERE m.team_id=? AND u.active=1 ORDER BY u.full_name', (t['id'],)).fetchall()) for t in teams]
        c.close(); return render_template('space.html', cards=cards, teams=teams, personal=personal, today=today, now_s=now(), sources=SOURCES, src=src, donec=donec, teams_opt=topt, only_team=False, next_url='/space', prios=PRIOS)
    @app.route('/space/team/<int:tid>', methods=['GET', 'POST'])
    @login_required
    def space_team(tid):
        u = current(); c = db(); role = team_role(c, u, tid)
        if not role: c.close(); audit('AccessDenied', 'Team', tid); return 'Access Denied', 403
        t = c.execute('SELECT * FROM teams WHERE id=?', (tid,)).fetchone(); manage = role in ('Lead', 'Admin')
        if request.method == 'POST':
            f = request.form; a = f.get('action'); uid = int(f['user_id']) if (f.get('user_id') or '').isdigit() else 0
            if not manage: c.close(); audit('AccessDenied', 'Team', tid); return 'Access Denied', 403
            scope,args=directory_scope_sql(u,D.get('org'),c)
            if a=='add_member' and not c.execute('SELECT 1 FROM users u WHERE u.id=? AND u.active=1 AND '+scope,[uid,*args]).fetchone(): c.close(); return 'Access Denied',403
            if a == 'add_member' and c.execute('SELECT 1 FROM users WHERE id=? AND active=1', (uid,)).fetchone():
                c.execute("INSERT OR IGNORE INTO team_members(team_id,user_id,role,added_at) VALUES(?,?, 'Member',?)", (tid, uid, now())); after(c, audit, 'AddMember', 'Team', tid, new=uid)
                after(c, notify, uid, 'U shtuat në ekip', 'Jeni shtuar në ekipin ' + t['name'], url_for('space_team', tid=tid))
            elif a == 'add_sector' and f.get('sector'):
                for r in c.execute("SELECT u.id FROM users u WHERE u.active=1 AND u.sector=? AND u.role!='Requester' AND "+scope, [f['sector'],*args]).fetchall(): c.execute("INSERT OR IGNORE INTO team_members(team_id,user_id,role,added_at) VALUES(?,?, 'Member',?)", (tid, r['id'], now()))
                after(c, audit, 'AddSector', 'Team', tid, new=f['sector'])
            elif a == 'remove_member' and uid != t['owner_id']:
                c.execute('DELETE FROM team_members WHERE team_id=? AND user_id=?', (tid, uid)); c.execute('UPDATE cards SET assignee_id=NULL WHERE assignee_id=? AND board_id IN (SELECT id FROM boards WHERE team_id=?)', (uid, tid)); after(c, audit, 'RemoveMember', 'Team', tid, old=uid)
            elif a == 'set_role' and f.get('role') in ('Lead', 'Member') and uid != t['owner_id']: c.execute('UPDATE team_members SET role=? WHERE team_id=? AND user_id=?', (f['role'], tid, uid)); after(c, audit, 'SetRole', 'Team', tid, new=f['role'])
            elif a == 'board_create' and f.get('name', '').strip(): make_board(c, tid, f['name'].strip(), u['id'])
            elif a == 'board_archive': c.execute('UPDATE boards SET archived=? WHERE id=? AND team_id=?', (1 if f.get('v') == '1' else 0, int(f.get('board_id') or 0), tid))
            elif a == 'team_update' and f.get('name', '').strip(): c.execute('UPDATE teams SET name=?,description=? WHERE id=?', (f['name'].strip()[:80], f.get('description', '')[:300], tid))
            elif a == 'team_delete' and f.get('confirm') and (t['owner_id'] == u['id'] or u['role'] in ('System Administrator', 'Central Administrator')):
                bs = [r['id'] for r in c.execute('SELECT id FROM boards WHERE team_id=?', (tid,))]
                for b in bs: c.execute('DELETE FROM cards WHERE board_id=?', (b,)); c.execute('DELETE FROM board_lists WHERE board_id=?', (b,))
                c.execute('DELETE FROM boards WHERE team_id=?', (tid,)); c.execute('DELETE FROM team_members WHERE team_id=?', (tid,)); c.execute('DELETE FROM teams WHERE id=?', (tid,)); c.commit(); c.close(); audit('Delete', 'Team', tid, old=t['name']); flash('Ekipi u fshi.', 'success'); return redirect(url_for('space'))
            c.commit(); c.close(); return redirect(url_for('space_team', tid=tid))
        members = c.execute('SELECT m.role,u.id,u.full_name,u.sector,u.structure FROM team_members m JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.role,u.full_name', (tid,)).fetchall()
        cand = c.execute("SELECT id,full_name,sector,structure FROM users WHERE active=1 AND role!='Requester' AND id NOT IN (SELECT user_id FROM team_members WHERE team_id=?) ORDER BY full_name", (tid,)).fetchall()
        scope,args=directory_scope_sql(u,D.get('org'),c)
        allowed={r[0] for r in c.execute('SELECT u.id FROM users u WHERE '+scope,args)}
        cand=[r for r in cand if r['id'] in allowed]
        sectors = [r['sector'] for r in c.execute("SELECT DISTINCT u.sector FROM users u WHERE u.active=1 AND u.sector<>'' AND "+scope+" ORDER BY u.sector",args)]
        boards = c.execute('SELECT b.*,(SELECT count(*) FROM cards k WHERE k.board_id=b.id) n FROM boards b WHERE team_id=? ORDER BY archived,id', (tid,)).fetchall(); s = stats(c, tid); c.close()
        topt = [dict(id=tid, name=t['name'], members=[dict(id=m['id'], full_name=m['full_name']) for m in members])]
        return render_template('space_team.html', t=t, members=members, cand=cand, sectors=sectors, boards=boards, manage=manage, s=s, role=role, sources=SOURCES, teams_opt=topt, only_team=True, next_url='/space/team/%d' % tid, prios=PRIOS)
    @app.route('/space/team/<int:tid>/dashboard')
    @login_required
    def space_dash(tid):
        u = current(); c = db()
        if not team_role(c, u, tid): c.close(); audit('AccessDenied', 'Team', tid); return 'Access Denied', 403
        t = c.execute('SELECT * FROM teams WHERE id=?', (tid,)).fetchone(); s = stats(c, tid); c.close(); return render_template('space_dash.html', t=t, s=s, now_s=now())
    @app.route('/space/board/<int:bid>', methods=['GET', 'POST'])
    @login_required
    def space_board(bid):
        u = current(); c = db(); b, mode = board_access(c, u, bid)
        if not b: c.close(); return 'Nuk u gjet', 404
        if not mode: c.close(); audit('AccessDenied', 'Board', bid); return 'Access Denied', 403
        team = c.execute('SELECT * FROM teams WHERE id=?', (b['team_id'],)).fetchone() if b['team_id'] else None
        people = c.execute('SELECT u.id,u.full_name FROM team_members m JOIN users u ON u.id=m.user_id WHERE m.team_id=? AND u.active=1 ORDER BY u.full_name', (b['team_id'],)).fetchall() if team else [dict(id=u['id'], full_name=u['full_name'])]
        pids = {p['id'] for p in people}
        if request.method == 'POST':
            if mode != 'write': c.close(); return 'Access Denied', 403
            f = request.form; a = f.get('action'); kid = int(f['card_id']) if (f.get('card_id') or '').isdigit() else 0
            lid = int(f['list_id']) if (f.get('list_id') or '').isdigit() else 0
            ok_list = lid and c.execute('SELECT is_done FROM board_lists WHERE id=? AND board_id=?', (lid, bid)).fetchone()
            asg = int(f['assignee_id']) if (f.get('assignee_id') or '').isdigit() and int(f['assignee_id']) in pids else None
            pr = f.get('priority') if f.get('priority') in PRIOS else 'Medium'
            if a == 'list_add' and f.get('name', '').strip(): c.execute('INSERT INTO board_lists(board_id,name,pos,is_done) VALUES(?,?,(SELECT COALESCE(MAX(pos),0)+1 FROM board_lists WHERE board_id=?),?)', (bid, f['name'].strip()[:60], bid, 1 if f.get('is_done') else 0))
            elif a == 'list_delete' and ok_list and not c.execute('SELECT 1 FROM cards WHERE list_id=?', (lid,)).fetchone(): c.execute('DELETE FROM board_lists WHERE id=?', (lid,))
            elif a == 'card_add' and ok_list and f.get('title', '').strip():
                kid = c.execute('INSERT INTO cards(board_id,list_id,title,description,assignee_id,creator_id,priority,due_at,created_at,completed_at,pos,source,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(pos),0)+1 FROM cards WHERE list_id=?),?,?)', (bid, lid, f['title'].strip()[:200], f.get('description', '')[:2000], asg, u['id'], pr, due(f.get('due')), now(), now() if ok_list['is_done'] else None, lid, *srcref(f))).lastrowid
                if asg and asg != u['id']: after(c, notify, asg, 'Detyrë e re në Hapësira ime', f['title'].strip()[:120] + ' (' + b['name'] + ')', url_for('space_board', bid=bid))
            elif a == 'card_update' and kid and ok_list:
                k = c.execute('SELECT * FROM cards WHERE id=? AND board_id=?', (kid, bid)).fetchone()
                if k:
                    comp = k['completed_at'] if ok_list['is_done'] and k['completed_at'] else (now() if ok_list['is_done'] else None)
                    c.execute('UPDATE cards SET title=?,description=?,assignee_id=?,priority=?,due_at=?,list_id=?,completed_at=?,source=?,source_ref=? WHERE id=?', (f.get('title', '').strip()[:200] or k['title'], f.get('description', '')[:2000], asg, pr, due(f.get('due')), lid, comp, *srcref(f), kid))
                    if asg and asg != k['assignee_id'] and asg != u['id']: after(c, notify, asg, 'Detyrë e re në Hapësira ime', k['title'][:120] + ' (' + b['name'] + ')', url_for('space_board', bid=bid))
            elif a == 'card_delete' and kid: c.execute('DELETE FROM cards WHERE id=? AND board_id=?', (kid, bid))
            elif a == 'board_rename' and f.get('name', '').strip(): c.execute('UPDATE boards SET name=? WHERE id=?', (f['name'].strip()[:80], bid))
            elif a == 'board_delete' and b['team_id'] is None and f.get('confirm'):
                c.execute('DELETE FROM cards WHERE board_id=?', (bid,)); c.execute('DELETE FROM board_lists WHERE board_id=?', (bid,)); c.execute('DELETE FROM boards WHERE id=?', (bid,)); c.commit(); c.close(); return redirect(url_for('space'))
            c.commit(); c.close(); return redirect(url_for('space_board', bid=bid))
        lists = [dict(l) for l in c.execute('SELECT * FROM board_lists WHERE board_id=? ORDER BY pos,id', (bid,))]
        cards = c.execute('SELECT k.*,u.full_name an FROM cards k LEFT JOIN users u ON u.id=k.assignee_id WHERE k.board_id=? ORDER BY k.pos,k.id', (bid,)).fetchall()
        for l in lists: l['cards'] = [k for k in cards if k['list_id'] == l['id']]
        c.close(); return render_template('space_board.html', b=b, team=team, lists=lists, people=people, mode=mode, now_s=now(), prios=PRIOS, sources=SOURCES)
    @app.route('/space/card/<int:kid>/move', methods=['POST'])
    @login_required
    def space_move(kid):
        u = current(); c = db(); j = request.get_json(silent=True) or {}; k = c.execute('SELECT * FROM cards WHERE id=?', (kid,)).fetchone()
        if not k: c.close(); return jsonify(error='Nuk u gjet'), 404
        b, mode = board_access(c, u, k['board_id'])
        if mode != 'write': c.close(); audit('AccessDenied', 'Card', kid); return jsonify(error='Access Denied'), 403
        l = c.execute('SELECT * FROM board_lists WHERE id=? AND board_id=?', (j.get('list_id'), k['board_id'])).fetchone()
        if not l: c.close(); return jsonify(error='Listë e pavlefshme'), 400
        ids = [r['id'] for r in c.execute('SELECT id FROM cards WHERE list_id=? AND id!=? ORDER BY pos,id', (l['id'], kid))]
        try: pos = max(0, min(int(j.get('pos', len(ids))), len(ids)))
        except (TypeError, ValueError): pos = len(ids)
        ids.insert(pos, kid)
        for i, x in enumerate(ids): c.execute('UPDATE cards SET pos=? WHERE id=?', (i, x))
        c.execute('UPDATE cards SET list_id=?,completed_at=? WHERE id=?', (l['id'], (k['completed_at'] or now()) if l['is_done'] else None, kid)); c.commit(); c.close(); return jsonify(ok=1)
