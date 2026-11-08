"""P1-05 tickets family. Pure import; instance dependencies are explicit."""

def register(runtime):

    def create_chain(tid, chain_users=(), chain_notes=()):
        """Krijon rrjedhën e veprimit (hapa të njëpasnjëshëm). Hapi 1 = përgjegjësi i zgjedhur; hapat pasues presin radhën."""
        c = runtime.db()
        tk = c.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
        ids = []
        if tk['assignee_id']:
            ids.append((tk['assignee_id'], ''))
        for i, x in enumerate(chain_users):
            if str(x).isdigit() and c.execute('SELECT 1 FROM users WHERE id=? AND active=1', (int(x),)).fetchone():
                ids.append((int(x), (chain_notes[i] if i < len(chain_notes) else '').strip()[:500]))
        if not ids:
            c.close()
            return
        if not tk['assignee_id']:
            c.execute('UPDATE tickets SET assignee_id=? WHERE id=?', (ids[0][0], tid))
        ts = runtime.now()
        for seq, (uid, ins) in enumerate(ids, 1):
            c.execute('INSERT INTO ticket_steps(ticket_id,seq,user_id,instruction,status,activated_at,created_at) VALUES(?,?,?,?,?,?,?)', (tid, seq, uid, ins, 'Active' if seq == 1 else 'Pending', ts if seq == 1 else None, ts))
        c.commit()
        c.close()
        runtime.event(tid, 'Workflow', f'Rrjedha e veprimit u krijua me {len(ids)} hap(a)')
        runtime.notify_actor(tid, ids[0][0], 'assigned')
    runtime.create_chain = create_chain

    def handle_step(c, tk, action):
        """Veprimet mbi rrjedhën: 'step_done' (nënshkrim + kalim te tjetri) dhe 'step_add' (shto hap)."""
        tid = tk['id']
        me = runtime.current()
        f = runtime.request.form
        back = runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
        if action == 'step_add':
            if not runtime.can_write(c, tk):
                c.close()
                runtime.audit('AccessDenied', 'Ticket', tid)
                return ('Access Denied', 403)
            uid = f.get('step_user', '')
            ins = f.get('step_instruction', '').strip()[:500]
            u = c.execute('SELECT * FROM users WHERE id=? AND active=1', (int(uid),)).fetchone() if uid.isdigit() else None
            if not u or tk['status'] == 'Closed':
                c.close()
                runtime.flash('Zgjidhni një përdorues aktiv (dhe ticket-i të mos jetë i mbyllur).', 'danger')
                return back
            if not runtime.can_delegate_user(me, u, tk['unit_id'], runtime.ORG, c):
                c.close()
                runtime.abort(403)
            ts = runtime.now()
            n = c.execute('SELECT count(*) n FROM ticket_steps WHERE ticket_id=?', (tid,)).fetchone()['n']
            activate = False
            if n == 0 and tk['assignee_id']:
                c.execute('INSERT INTO ticket_steps(ticket_id,seq,user_id,instruction,status,activated_at,created_at) VALUES(?,?,?,?,?,?,?)', (tid, 1, tk['assignee_id'], 'Caktimi fillestar', 'Active', ts, ts))
                n = 1
            live = c.execute("SELECT count(*) n FROM ticket_steps WHERE ticket_id=? AND status IN ('Active','Pending')", (tid,)).fetchone()['n']
            seq = c.execute('SELECT COALESCE(MAX(seq),0) m FROM ticket_steps WHERE ticket_id=?', (tid,)).fetchone()['m'] + 1
            activate = live == 0
            c.execute('INSERT INTO ticket_steps(ticket_id,seq,user_id,instruction,status,activated_at,created_at) VALUES(?,?,?,?,?,?,?)', (tid, seq, u['id'], ins, 'Active' if activate else 'Pending', ts if activate else None, ts))
            if activate:
                c.execute("UPDATE tickets SET assignee_id=?,status=CASE WHEN status IN ('Resolved') THEN 'In Progress' ELSE status END,resolved_at=CASE WHEN status='Resolved' THEN NULL ELSE resolved_at END WHERE id=?", (u['id'], tid))
            c.commit()
            c.close()
            runtime.event(tid, 'Workflow', f"U shtua hapi {seq}: {u['full_name']}")
            runtime.audit('StepAdd', 'Ticket', tid, new=u['full_name'])
            if activate:
                runtime.notify_actor(tid, u['id'], 'turn')
            runtime.flash('Hapi u shtua në rrjedhë.', 'success')
            return back
        st = c.execute("SELECT * FROM ticket_steps WHERE ticket_id=? AND status='Active' ORDER BY seq LIMIT 1", (tid,)).fetchone()
        note = f.get('note', '').strip()[:2000]
        if not st or me['role'] == 'Auditor' or tk['status'] == 'Closed' or (st['user_id'] != me['id'] and me['role'] != 'System Administrator'):
            c.close()
            runtime.audit('AccessDenied', 'Ticket', tid)
            return ('Access Denied', 403)
        if not note:
            c.close()
            runtime.flash('Shënimi i nënshkrimit është i detyrueshëm.', 'danger')
            return back
        ts = runtime.now()
        c.execute("UPDATE ticket_steps SET status='Done',note=?,signed_by=?,signed_at=? WHERE id=?", (note, me['full_name'], ts, st['id']))
        nxt = c.execute("SELECT * FROM ticket_steps WHERE ticket_id=? AND status='Pending' ORDER BY seq LIMIT 1", (tid,)).fetchone()
        msg = ''
        resolved = False
        if nxt:
            c.execute("UPDATE ticket_steps SET status='Active',activated_at=? WHERE id=?", (ts, nxt['id']))
            c.execute("UPDATE tickets SET assignee_id=?,status=CASE WHEN status IN ('Open','Assigned','Waiting') THEN 'In Progress' ELSE status END WHERE id=?", (nxt['user_id'], tid))
        elif c.execute("SELECT 1 FROM tasks WHERE ticket_id=? AND status!='Completed'", (tid,)).fetchone():
            msg = 'Hapi i fundit u nënshkrua, por ticket-i mbetet i hapur sepse ka task-e të pambyllura.'
        elif tk['status'] not in ('Resolved', 'Closed'):
            c.execute("UPDATE tickets SET status='Resolved',resolved_at=? WHERE id=?", (ts, tid))
            resolved = True
        c.commit()
        req = tk['requester_id']
        code = tk['code']
        c.close()
        runtime.event(tid, 'Signature', f"{me['full_name']} nënshkroi hapin {st['seq']}: {note[:300]}")
        runtime.audit('StepDone', 'Ticket', tid, new=f"hap {st['seq']}")
        if resolved:
            runtime.event(tid, 'Status', 'Të gjithë hapat u nënshkruan → Resolved')
            runtime.audit('Status', 'Ticket', tid, tk['status'], 'Resolved')
        if nxt:
            runtime.notify_actor(tid, nxt['user_id'], 'turn')
        if resolved and req and (req != me['id']):
            runtime.notify(req, f'Ticket i zgjidhur – {code}', 'Të gjithë hapat e rrjedhës u përfunduan.', f'/tickets/{tid}', 'info')
        runtime.flash(msg or ('Nënshkrimi u regjistrua. Ticket-i iu kalua përgjegjësit tjetër.' if nxt else 'Nënshkrimi u regjistrua. Rrjedha përfundoi.'), 'success')
        return back
    runtime.handle_step = handle_step

    @runtime.login_required
    def new_ticket():
        if runtime.request.method == 'POST' and (runtime.current()['role'] not in runtime.ROLES or runtime.current()['role'] == 'Auditor'):
            return ('Access Denied', 403)
        c = runtime.db()
        users = c.execute('SELECT * FROM users WHERE active=1 ORDER BY full_name').fetchall()
        services = c.execute('SELECT * FROM services ORDER BY name').fetchall()
        if runtime.request.method == 'POST':
            if runtime.current()['role'] in ('Requester', 'Management') and (runtime.request.form.get('assignee_id') or runtime.request.form.getlist('chain_users')):
                c.close()
                return ('Access Denied', 403)
            requester = runtime.current()['role'] in ('Requester', 'Management')
            service_id = runtime.request.form.get('service_id') or None
            route_unit = runtime.request.form.get('unit_id')
            structure = runtime.request.form.get('structure', '')
            if requester:
                if any((len(runtime.request.form.getlist(k)) > 1 for k in ('unit_id', 'service_id', 'assignee_id'))):
                    c.close()
                    return ('Invalid routing request', 400)
                if route_unit:
                    c.close()
                    return ('Access Denied', 403)
                if service_id:
                    if not service_id.isascii() or not service_id.isdigit() or int(service_id) <= 0:
                        c.close()
                        return ('Invalid service', 400)
                    service = c.execute('SELECT * FROM services WHERE id=?', (int(service_id),)).fetchone()
                    if not service:
                        c.close()
                        return ('Invalid service', 400)
                    service_scope, service_args = runtime.service_read_scope_sql(runtime.current(), runtime.ORG, c)
                    if not c.execute('SELECT 1 FROM services s WHERE s.id=? AND ' + service_scope, [int(service_id), *service_args]).fetchone():
                        c.close()
                        runtime.abort(403)
                    if service['unit_id'] is not None and service['unit_id'] not in runtime.ORG.scope_ids(c, runtime.current()):
                        c.close()
                        return ('Access Denied', 403)
                intake = runtime.setting('intake_unit_id', '')
                if not str(intake).isascii() or not str(intake).isdigit() or (not c.execute('SELECT 1 FROM org_units WHERE id=?', (int(intake),)).fetchone()):
                    c.close()
                    return ('Ticket intake is not configured', 503)
                route_unit = int(intake)
                structure = runtime.current()['structure'] or ''
            if not requester:
                if any((len(runtime.request.form.getlist(k)) > 1 for k in ('unit_id', 'service_id', 'assignee_id'))):
                    c.close()
                    runtime.abort(400)

                def selected_id(value):
                    if not value:
                        return None
                    if not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
                        c.close()
                        runtime.abort(400)
                    return int(value)
                route_unit = selected_id(route_unit)
                service_id = selected_id(service_id)
                if service_id:
                    svc = c.execute('SELECT * FROM services WHERE id=?', (service_id,)).fetchone()
                    if not svc:
                        c.close()
                        runtime.abort(400)
                    service_scope, service_args = runtime.service_read_scope_sql(runtime.current(), runtime.ORG, c)
                    if not c.execute('SELECT 1 FROM services s WHERE s.id=? AND ' + service_scope, [service_id, *service_args]).fetchone():
                        c.close()
                        runtime.abort(403)
                    if runtime.current()['role'] != 'System Administrator' and svc['unit_id'] is not None and (svc['unit_id'] not in runtime.ORG.scope_ids(c, runtime.current())):
                        c.close()
                        runtime.abort(403)
                    if not route_unit:
                        route_unit = svc['unit_id']
                if not route_unit:
                    route_unit = runtime.current()['org_unit_id'] or selected_id(runtime.setting('intake_unit_id', ''))
                if not route_unit or not c.execute('SELECT 1 FROM org_units WHERE id=?', (route_unit,)).fetchone():
                    c.close()
                    runtime.abort(400)
                if runtime.current()['role'] != 'System Administrator' and route_unit not in runtime.ORG.scope_ids(c, runtime.current()):
                    c.close()
                    runtime.abort(403)
                for raw in ([runtime.request.form.get('assignee_id')] if runtime.request.form.get('assignee_id') else []) + runtime.request.form.getlist('chain_users'):
                    uid = selected_id(raw)
                    target = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
                    if not runtime.can_delegate_user(runtime.current(), target, route_unit, runtime.ORG, c):
                        c.close()
                        runtime.abort(403)
            typ = runtime.request.form.get('type')
            pri = runtime.request.form.get('priority')
            if typ not in runtime.TYPES or pri not in runtime.PRIOS or (not runtime.request.form.get('title', '').strip()):
                c.close()
                runtime.flash('Të dhëna të pavlefshme (kategoria, prioriteti dhe titulli janë të detyrueshme).', 'danger')
                return runtime.redirect(runtime.url_for('new_ticket'))
            prefix = {'Incident': 'INC', 'Service Request': 'REQ', 'Task': 'TSK', 'Problem': 'PRB', 'Change': 'CHG'}.get(typ, 'TKT')
            code = 'TMP-' + runtime.secrets.token_hex(6)
            sh = runtime.request.form.get('sla_hours') or '24'
            due = runtime.add_business_hours(runtime.datetime.now(), min(max(int(sh) if sh.isdigit() else 24, 1), 720)).strftime('%Y-%m-%d %H:%M:%S')
            cur = c.execute('INSERT INTO tickets(code,type,title,description,category,service_id,structure,priority,status,requester_id,assignee_id,created_by,created_at,due_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (code, typ, runtime.request.form['title'], runtime.request.form['description'], runtime.request.form.get('category', ''), service_id, structure, runtime.request.form['priority'], 'Open', runtime.session['uid'], runtime.request.form.get('assignee_id') or None, runtime.session['uid'], runtime.now(), due))
            tid = cur.lastrowid
            code = f'{prefix}-{runtime.datetime.now().year}-{tid:05d}'
            c.execute('UPDATE tickets SET code=? WHERE id=?', (code, tid))
            runtime.ORG.route(c, tid, route_unit, None if requester else service_id) if runtime.ORG else None
            c.commit()
            c.close()
            runtime.audit('Create', 'Ticket', tid, new=runtime.request.form['title'][:200])
            runtime.event(tid, 'Created', f'Ticket {code} u krijua')
            runtime.create_chain(tid, runtime.request.form.getlist('chain_users'), runtime.request.form.getlist('chain_notes'))
            return runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
        requester = runtime.current()['role'] in ('Requester', 'Management')
        if requester:
            ids = runtime.ORG.scope_ids(c, runtime.current())
            services = [r for r in services if r['unit_id'] is None or r['unit_id'] in ids]
        services = runtime.visible_services(c, services)
        preset = runtime.request.args.get('type', '')
        oo = runtime.ORG.options(c) if runtime.ORG else []
        oo = [o for o in oo if runtime.current()['role'] == 'System Administrator' or o['id'] in runtime.ORG.scope_ids(c, runtime.current())]
        users = runtime.visible_users(c, users)
        c.close()
        return runtime.render_template('ticket_form.html', org_options=[] if requester else oo, is_requester=requester, users=users, services=services, preset=preset if preset in runtime.TYPES else '', me_id=runtime.session['uid'])
    runtime.new_ticket = new_ticket

    @runtime.login_required
    def ticket_detail(tid):
        c = runtime.db()
        tk = c.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
        if not tk:
            c.close()
            return ('Nuk u gjet', 404)
        if not runtime.can_view(c, tk):
            c.close()
            runtime.audit('AccessDenied', 'Ticket', tid)
            return ('Access Denied', 403)
        if runtime.request.method == 'POST':
            if not runtime.can_write(c, tk):
                c.close()
                runtime.audit('AccessDenied', 'Ticket', tid)
                return ('Access Denied', 403)
            action = runtime.request.form.get('action')
            if runtime.current()['role'] == 'Requester' and action != 'comment':
                c.close()
                runtime.audit('AccessDenied', 'Ticket', tid)
                return ('Access Denied', 403)
            if action in ('step_done', 'step_add'):
                return runtime.handle_step(c, tk, action)
            if action == 'comment':
                c.close()
                runtime.event(tid, 'Comment', runtime.request.form['comment'][:3000])
                runtime.audit('Comment', 'Ticket', tid)
                return runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
            if action == 'status':
                old = tk['status']
                new = runtime.request.form.get('status', '')
                back = runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
                note = (runtime.request.form.get('resolution_note') or runtime.request.form.get('completion_notes') or '').strip()[:2000]
                src = 'Open' if old == 'New' else old
                if new not in runtime.TRANS:
                    c.close()
                    runtime.flash('Status i pavlefshëm.', 'danger')
                    return back
                if new != old:
                    path = runtime.status_path(src, new)
                    if not path:
                        c.close()
                        runtime.flash(f'Tranzicion i palejuar: {old} → {new}', 'danger')
                        return back
                    if new in ('Resolved', 'Closed') and len(note) < 5:
                        c.close()
                        runtime.flash('Për të zgjidhur/mbyllur ticket-in duhet një përshkrim i shkurtër i asaj që u bë (min. 5 shkronja).', 'danger')
                        return back
                    if new in ('Resolved', 'Closed') and c.execute("SELECT 1 FROM ticket_steps WHERE ticket_id=? AND status IN ('Active','Pending')", (tid,)).fetchone():
                        c.close()
                        runtime.flash('Complete the active workflow before closing the ticket.', 'danger')
                        return back
                    if new in ('Resolved', 'Closed') and c.execute("SELECT 1 FROM tasks WHERE ticket_id=? AND status!='Completed'", (tid,)).fetchone():
                        c.close()
                        runtime.flash('Ka task-e të pambyllura.', 'danger')
                        return back
                    ts = runtime.now()
                    prev = old
                    steps_log = []
                    for st_ in path:
                        c.execute("UPDATE tickets SET status=?,resolved_at=CASE WHEN ?='Resolved' THEN ? ELSE resolved_at END,closed_at=CASE WHEN ?='Closed' THEN ? ELSE closed_at END WHERE id=?", (st_, st_, ts, st_, ts, tid))
                        steps_log.append((prev, st_))
                        prev = st_
                    if new in ('Resolved', 'Closed'):
                        c.execute('UPDATE tickets SET resolution_note=? WHERE id=?', (note, tid))
                    c.commit()
                    c.close()
                    for i, (x, y) in enumerate(steps_log):
                        runtime.event(tid, 'Status', f'{x} → {y}' + (f' — {note}' if note and i == len(steps_log) - 1 else ''))
                        runtime.audit('Status', 'Ticket', tid, x, y + (f' | {note[:300]}' if note and i == len(steps_log) - 1 else ''))
                    if new == 'Closed':
                        runtime.notify_closed(tid, runtime.session['uid'], note)
                    return back
                c.close()
                return back
            if action == 'task':
                newid, err = runtime.create_task(c, tid, runtime.request.form)
                c.close()
                if err:
                    runtime.flash(err, 'danger')
                    return runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
                runtime.after_task_created(newid, tid)
                runtime.flash('Detyra u krijua, u caktua dhe iu dërgua njoftim.', 'success')
                return runtime.redirect(runtime.url_for('ticket_detail', tid=tid))
        t = c.execute('SELECT t.*,s.name service,u.full_name assignee FROM tickets t LEFT JOIN services s ON s.id=t.service_id LEFT JOIN users u ON u.id=t.assignee_id WHERE t.id=?', (tid,)).fetchone()
        tasks = c.execute('SELECT ta.*,g.name group_name,(SELECT group_concat(u.full_name, ", ") FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=ta.id) assignees FROM tasks ta LEFT JOIN support_groups g ON g.id=ta.group_id WHERE ticket_id=? ORDER BY ta.id', (tid,)).fetchall()
        timeline = c.execute('SELECT tl.*,u.full_name actor FROM timeline tl LEFT JOIN users u ON u.id=tl.actor_id WHERE ticket_id=? ORDER BY tl.id DESC', (tid,)).fetchall()
        users = c.execute('SELECT * FROM users WHERE active=1 ORDER BY full_name').fetchall()
        groups = c.execute('SELECT * FROM support_groups ORDER BY name').fetchall()
        gopts = runtime.group_options(c)
        steps = c.execute('SELECT st.*,u.full_name,u.email FROM ticket_steps st LEFT JOIN users u ON u.id=st.user_id WHERE st.ticket_id=? ORDER BY st.seq', (tid,)).fetchall()
        users = runtime.visible_users(c, users)
        me = runtime.current()
        act = next((x for x in steps if x['status'] == 'Active'), None)
        my_step = bool(act) and me['role'] in runtime.STAFF_ROLES and (tk['status'] != 'Closed') and (act['user_id'] == me['id'] or me['role'] == 'System Administrator')
        can_edit = runtime.can_write(c, tk)
        mytasks = c.execute('SELECT task_id FROM task_assignees WHERE user_id=?', (me['id'],)).fetchall()
        c.close()
        return runtime.render_template('ticket_detail.html', t=t, tasks=tasks, timeline=timeline, users=users, groups=groups, group_opts=gopts, steps=steps, my_step=my_step, can_edit=can_edit, me=me, my_task_ids={r['task_id'] for r in mytasks})
    runtime.ticket_detail = ticket_detail

    def status_path(old, new):
        """Rruga e lejuar e statuseve. Për Resolved/Closed lejohen hapa ndërmjetës (p.sh. Open→In Progress→Resolved)."""
        if old == new:
            return []
        if new in runtime.TRANS.get(old, []):
            return [new]
        if new not in ('Resolved', 'Closed'):
            return None
        seen = {old: None}
        q = [old]
        while q:
            x = q.pop(0)
            for y in runtime.TRANS.get(x, []):
                if y in seen:
                    continue
                seen[y] = x
                if y == new:
                    p = [y]
                    while seen[p[-1]]:
                        p.append(seen[p[-1]])
                    return [z for z in reversed(p) if z != old]
                q.append(y)
        return None
    runtime.status_path = status_path

    def group_options(c):
        names = {r['name'] for r in c.execute('SELECT name FROM support_groups')}
        for r in c.execute('SELECT sector,structure FROM users WHERE active=1'):
            for k in ('sector', 'structure'):
                if r[k] and r[k].strip():
                    names.add(r[k].strip())
        return sorted(names, key=lambda x: x.lower())
    runtime.group_options = group_options

    def task_event(taskid, typ, details, actor='me'):
        uid = runtime.session.get('uid') if actor == 'me' else actor
        c = runtime.db()
        c.execute('INSERT INTO task_events(task_id,actor_id,event_type,details,created_at) VALUES(?,?,?,?,?)', (taskid, uid, typ, str(details)[:2000], runtime.now()))
        c.commit()
        c.close()
    runtime.task_event = task_event

    def safe_back(default):
        try:
            ref = runtime.urlparse(runtime.request.referrer or '')
            if ref.netloc == runtime.request.host and ref.path.startswith('/') and (not ref.path.startswith('//')) and ('\\' not in ref.path):
                return ref.path + ('?' + ref.query if ref.query else '')
        except Exception:
            pass
        return default
    runtime.safe_back = safe_back

    def create_task(c, tid, f, parent=None):
        title = (f.get('task_title') or '').strip()[:200]
        if not title:
            return (None, 'Titulli i detyrës është i detyrueshëm.')
        uids = []
        tk = c.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
        if not tk or tk['status'] == 'Closed':
            c.close()
            runtime.abort(403)
        for x in f.getlist('task_assignees'):
            if not x.isascii() or not x.isdigit() or int(x) <= 0:
                c.close()
                runtime.abort(400)
            target = c.execute('SELECT * FROM users WHERE id=?', (int(x),)).fetchone()
            if not runtime.can_delegate_user(runtime.current(), target, tk['unit_id'], runtime.ORG, c):
                c.close()
                runtime.abort(403)
            if int(x) not in uids:
                uids.append(int(x))
        if not uids:
            return (None, 'Select an authorized assignee.')
        gname = (f.get('task_group') or '').strip()[:100]
        gid = None
        if gname:
            r = c.execute('SELECT id FROM support_groups WHERE id=?', (int(gname),)).fetchone() if gname.isdigit() else None
            if not r:
                r = c.execute('SELECT id FROM support_groups WHERE lower(name)=lower(?)', (gname,)).fetchone()
            if not r:
                c.execute('INSERT OR IGNORE INTO support_groups(name) VALUES(?)', (gname,))
                r = c.execute('SELECT id FROM support_groups WHERE name=?', (gname,)).fetchone()
            gid = r['id'] if r else None
        prio = f.get('task_priority', 'Medium')
        prio = prio if prio in runtime.PRIOS else 'Medium'
        cur = c.execute('INSERT INTO tasks(ticket_id,title,description,group_id,priority,status,due_at,created_at,parent_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)', (tid, title, (f.get('task_description') or '').strip()[:3000], gid, prio, 'Open', f.get('task_due') or None, runtime.now(), parent, runtime.session.get('uid')))
        taskid = cur.lastrowid
        for x in uids:
            c.execute('INSERT OR IGNORE INTO task_assignees(task_id,user_id) VALUES(?,?)', (taskid, x))
        c.commit()
        return (taskid, None)
    runtime.create_task = create_task

    def after_task_created(taskid, tid, parent=None):
        c = runtime.db()
        t = c.execute('SELECT title FROM tasks WHERE id=?', (taskid,)).fetchone()
        names = ', '.join((r['full_name'] for r in c.execute('SELECT u.full_name FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=? ORDER BY u.full_name', (taskid,))))
        c.close()
        me = runtime.current()['full_name']
        runtime.task_event(taskid, 'Created', f'Detyra u krijua nga {me}' + (' si nën-detyrë' if parent else ''))
        runtime.task_event(taskid, 'Assigned', f'Iu caktua: {names}')
        if parent:
            runtime.task_event(parent, 'Subtask', f"U shtua nën-detyra «{t['title']}» (caktuar: {names})")
        runtime.event(tid, 'Task', f"Detyra «{t['title']}» u krijua nga {me} dhe iu caktua: {names}")
        runtime.audit('TaskCreate', 'Task', taskid, new=t['title'])
        runtime.notify_task(taskid)
    runtime.after_task_created = after_task_created

    def load_task(c, taskid):
        t = c.execute('SELECT ta.*,tk.code ticket_code,tk.title ticket_title,tk.status ticket_status,g.name group_name,cu.full_name creator FROM tasks ta JOIN tickets tk ON tk.id=ta.ticket_id LEFT JOIN support_groups g ON g.id=ta.group_id LEFT JOIN users cu ON cu.id=ta.created_by WHERE ta.id=?', (taskid,)).fetchone()
        if not t:
            return (None, None, False, False)
        tk = c.execute('SELECT * FROM tickets WHERE id=?', (t['ticket_id'],)).fetchone()
        if not runtime.can_view(c, tk):
            return (t, tk, False, False)
        mine = bool(c.execute('SELECT 1 FROM task_assignees WHERE task_id=? AND user_id=?', (taskid, runtime.current()['id'])).fetchone())
        return (t, tk, True, tk['status'] != 'Closed' and runtime.current()['role'] in runtime.STAFF_ROLES and (mine or runtime.can_write(c, tk)))
    runtime.load_task = load_task

    @runtime.login_required
    def task_detail(taskid):
        c = runtime.db()
        t, tk, see, act = runtime.load_task(c, taskid)
        if not t:
            c.close()
            return ('Nuk u gjet', 404)
        if not see:
            c.close()
            runtime.audit('AccessDenied', 'Task', taskid)
            return ('Access Denied', 403)
        assg = c.execute('SELECT u.id,u.full_name,u.email,u.duty,u.role FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=? ORDER BY u.full_name', (taskid,)).fetchall()
        ev = [dict(r) for r in c.execute('SELECT e.*,u.full_name actor FROM task_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.task_id=? ORDER BY e.id', (taskid,))]
        names = ', '.join((a['full_name'] for a in assg))
        types = {e['event_type'] for e in ev}
        pre = []
        post = []
        if 'Created' not in types:
            pre.append(dict(event_type='Created', details='Detyra u krijua' + (f" nga {t['creator']}" if t['creator'] else ''), actor=t['creator'], created_at=t['created_at'], synthetic=1))
        if 'Assigned' not in types and names:
            pre.append(dict(event_type='Assigned', details='Iu caktua: ' + names, actor=t['creator'], created_at=t['created_at'], synthetic=1))
        if t['status'] == 'Completed' and 'Completed' not in types:
            post.append(dict(event_type='Completed', details=t['completion_notes'] or '', actor=None, created_at=t['completed_at'], synthetic=1))
        subs = c.execute('SELECT ta.*,(SELECT group_concat(u.full_name, ", ") FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=ta.id) assignees FROM tasks ta WHERE ta.parent_id=? ORDER BY ta.id', (taskid,)).fetchall()
        parent = c.execute('SELECT id,title FROM tasks WHERE id=?', (t['parent_id'],)).fetchone() if t['parent_id'] else None
        users = c.execute('SELECT * FROM users WHERE active=1 ORDER BY full_name').fetchall()
        gopts = runtime.group_options(c)
        users = runtime.visible_users(c, users)
        c.close()
        return runtime.render_template('task_detail.html', t=t, assignees=assg, events=pre + ev + post, subs=subs, parent=parent, users=users, group_opts=gopts, can_act=act, icons=runtime.TASK_ICONS, open_subs=sum((1 for x in subs if x['status'] != 'Completed')))
    runtime.task_detail = task_detail

    @runtime.login_required
    def complete_task(taskid):
        notes = (runtime.request.form.get('completion_notes') or '').strip()[:1000]
        c = runtime.db()
        t, tk, see, act = runtime.load_task(c, taskid)
        if not t or not see or (not act):
            c.close()
            runtime.audit('AccessDenied', 'Task', taskid)
            return ('Access Denied', 403)
        back = runtime.redirect(runtime.safe_back(runtime.url_for('task_detail', taskid=taskid)))
        if t['status'] == 'Completed':
            c.close()
            return back
        if len(notes) < 5:
            c.close()
            runtime.flash('Përshkrimi i shkurtër i asaj që u bë është i detyrueshëm (min. 5 shkronja).', 'danger')
            return back
        if c.execute("SELECT 1 FROM tasks WHERE parent_id=? AND status!='Completed'", (taskid,)).fetchone():
            c.close()
            runtime.flash('Kjo detyrë ka nën-detyra të pambyllura. Mbyllini së pari ato.', 'danger')
            return back
        c.execute("UPDATE tasks SET status='Completed',completed_at=?,completion_notes=? WHERE id=?", (runtime.now(), notes, taskid))
        c.commit()
        rcpt = {x for x in (t['created_by'], tk['assignee_id'], tk['requester_id']) if x and x != runtime.session['uid']}
        c.close()
        me = runtime.current()['full_name']
        runtime.task_event(taskid, 'Completed', notes)
        runtime.event(t['ticket_id'], 'Task', f"Detyra «{t['title']}» u përfundua nga {me}: {notes}")
        runtime.audit('TaskComplete', 'Task', taskid, new=notes[:300])
        for r in rcpt:
            runtime.notify(r, f"Detyra u përfundua – {t['title']}", f'{me}: {notes[:200]}', f'/tasks/{taskid}', 'task')
        runtime.flash('Detyra u mbyll me sukses.', 'success')
        return back
    runtime.complete_task = complete_task

    @runtime.login_required
    def task_do(taskid):
        c = runtime.db()
        t, tk, see, act = runtime.load_task(c, taskid)
        if not t or not see or (not act):
            c.close()
            runtime.audit('AccessDenied', 'Task', taskid)
            return ('Access Denied', 403)
        a = runtime.request.form.get('action')
        f = runtime.request.form
        back = runtime.redirect(runtime.url_for('task_detail', taskid=taskid))
        done = t['status'] == 'Completed'
        if a == 'start':
            if t['status'] != 'Open':
                c.close()
                runtime.flash('Detyra është tashmë në proces ose e përfunduar.', 'danger')
                return back
            c.execute("UPDATE tasks SET status='In Progress',started_at=? WHERE id=?", (runtime.now(), taskid))
            c.commit()
            c.close()
            runtime.task_event(taskid, 'Started', 'Filloi punën')
            runtime.event(t['ticket_id'], 'Task', f"Detyra «{t['title']}» filloi")
            runtime.audit('TaskStart', 'Task', taskid)
            runtime.flash('Detyra kaloi në proces.', 'success')
            return back
        if a == 'update':
            note = (f.get('note') or '').strip()[:1000]
            if done or len(note) < 3:
                c.close()
                runtime.flash('Shkruani një shënim (min. 3 shkronja) në një detyrë të pambyllur.', 'danger')
                return back
            c.close()
            runtime.task_event(taskid, 'Update', note)
            runtime.audit('TaskUpdate', 'Task', taskid, new=note[:200])
            runtime.flash('Shënimi u shtua në timeline.', 'success')
            return back
        if a == 'reopen':
            note = (f.get('note') or '').strip()[:1000]
            if not done or len(note) < 5:
                c.close()
                runtime.flash('Për ta rihapur duhet një arsye (min. 5 shkronja).', 'danger')
                return back
            c.execute("UPDATE tasks SET status='In Progress',completed_at=NULL WHERE id=?", (taskid,))
            c.commit()
            c.close()
            runtime.task_event(taskid, 'Reopened', note)
            runtime.audit('TaskReopen', 'Task', taskid, new=note[:200])
            runtime.flash('Detyra u rihap.', 'success')
            return back
        if a == 'subtask':
            if done:
                c.close()
                runtime.flash('Nuk mund të shtohet nën-detyrë në një detyrë të përfunduar.', 'danger')
                return back
            newid, err = runtime.create_task(c, t['ticket_id'], f, parent=taskid)
            c.close()
            if err:
                runtime.flash(err, 'danger')
                return back
            runtime.after_task_created(newid, t['ticket_id'], parent=taskid)
            runtime.flash('Nën-detyra u krijua dhe iu dërgua njoftim.', 'success')
            return back
        c.close()
        runtime.flash('Veprim i pavlefshëm.', 'danger')
        return back
    runtime.task_do = task_do
