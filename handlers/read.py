"""P1-05 read family. Pure import; instance dependencies are explicit."""

def register(runtime):

    def workload_rows(c, u, limit=None):
        """Workload includes open tickets, tasks, active workflow steps and workspace cards, with overdue counts."""
        n = runtime.now()
        w = "u.active=1 AND u.role!='Requester'"
        p = {'n': n}
        if runtime.ORG:
            uf = runtime.ORG.user_filter(c, u)
            if uf:
                w += ' AND ' + uf[0]
                p.update(uf[1])
        elif u['role'] not in runtime.GLOBAL:
            w += " AND (u.id=:uid OR (u.structure<>'' AND u.structure=:st))"
            p.update(uid=u['id'], st=u['structure'])
        ticket_scope, scope_args = runtime.ticket_scope_sql(u, runtime.ORG, c)
        for i, value in enumerate(scope_args):
            ticket_scope = ticket_scope.replace('?', ':scope' + str(i), 1)
            p['scope' + str(i)] = value
        visible_tickets = 'SELECT t.id FROM tickets t WHERE ' + ticket_scope
        board_ids = []
        for b in c.execute('SELECT id FROM boards').fetchall():
            if runtime._D['space_board_access'](c, u, b['id'])[1]:
                key = 'board' + str(len(board_ids))
                p[key] = b['id']
                board_ids.append(':' + key)
        visible_boards = ','.join(board_ids) or 'NULL'
        rows = [dict(r) for r in c.execute(f"SELECT u.id,u.full_name,u.sector,\n (SELECT count(*) FROM tickets t WHERE t.id IN ({visible_tickets}) AND t.assignee_id=u.id AND t.status NOT IN ('Resolved','Closed')) tk,\n (SELECT count(*) FROM task_assignees x JOIN tasks ta ON ta.id=x.task_id WHERE ta.ticket_id IN ({visible_tickets}) AND x.user_id=u.id AND ta.status!='Completed') ts,\n (SELECT count(*) FROM ticket_steps s JOIN tickets t ON t.id=s.ticket_id WHERE t.id IN ({visible_tickets}) AND s.user_id=u.id AND s.status='Active' AND t.status NOT IN ('Resolved','Closed')) st,\n (SELECT count(*) FROM cards k JOIN board_lists l ON l.id=k.list_id JOIN boards b ON b.id=k.board_id WHERE b.id IN ({visible_boards}) AND k.assignee_id=u.id AND l.is_done=0 AND b.archived=0) cd,\n (SELECT count(*) FROM tickets t WHERE t.id IN ({visible_tickets}) AND t.assignee_id=u.id AND t.status NOT IN ('Resolved','Closed') AND t.due_at<:n)\n +(SELECT count(*) FROM task_assignees x JOIN tasks ta ON ta.id=x.task_id WHERE ta.ticket_id IN ({visible_tickets}) AND x.user_id=u.id AND ta.status!='Completed' AND ta.due_at IS NOT NULL AND ta.due_at<:n)\n +(SELECT count(*) FROM cards k JOIN board_lists l ON l.id=k.list_id JOIN boards b ON b.id=k.board_id WHERE b.id IN ({visible_boards}) AND k.assignee_id=u.id AND l.is_done=0 AND b.archived=0 AND k.due_at<:n) od\n FROM users u WHERE {w}", p)]
        for r in rows:
            r['total'] = r['tk'] + r['ts'] + r['st'] + r['cd']
        rows.sort(key=lambda r: (-r['total'], r['full_name']))
        return rows[:limit] if limit else rows
    runtime.workload_rows = workload_rows

    def _norm(s):
        return ''.join((ch for ch in runtime._ud.normalize('NFKD', str(s or '')) if not runtime._ud.combining(ch))).casefold()
    runtime._norm = _norm

    @runtime.login_required
    def api_users_search():
        """Search all user fields without case or diacritic sensitivity."""
        q = runtime._norm((runtime.request.args.get('q') or '')[:80])
        terms = q.split()[:6]
        lim = int(runtime.request.args.get('limit')) if (runtime.request.args.get('limit') or '').isdigit() else 15
        lim = max(1, min(lim, 50))
        c = runtime.db()
        scope, params = runtime.directory_scope_sql(runtime.current(), runtime.ORG, c)
        rows = c.execute('SELECT u.id,u.full_name,u.username,u.role,u.sector,u.structure,u.duty,u.institution,u.email,u.phone,o.name unit FROM users u LEFT JOIN org_units o ON o.id=u.org_unit_id WHERE u.active=1 AND ' + scope + ' ORDER BY u.full_name', params).fetchall()
        c.close()
        me = runtime.session.get('uid')
        out = []
        for r in rows:
            if runtime.request.args.get('self') == '0' and r['id'] == me:
                continue
            d = dict(r)
            hay = runtime._norm(' '.join((str(d.get(k) or '') for k in ('full_name', 'username', 'email', 'phone', 'role', 'sector', 'structure', 'duty', 'institution', 'unit'))))
            if all((t in hay for t in terms)):
                d['_rank'] = 0 if runtime._norm(d['full_name']).startswith(q) and q else 1
                out.append(d)
        out.sort(key=lambda d: (d['_rank'], runtime._norm(d['full_name'])))
        for d in out:
            d.pop('_rank', None)
        return runtime.jsonify(out[:lim])
    runtime.api_users_search = api_users_search

    @runtime.login_required
    def dashboard():
        c = runtime.db()
        u_ = runtime.current()
        vsql, vargs = runtime.vis_ticket_sql(u_)
        vis = c.execute(f'SELECT t.type,t.status,t.due_at,t.created_at FROM tickets t WHERE {vsql}', vargs).fetchall()
        nows = runtime.now()
        total = len(vis)
        counts = {}
        matrix_d = {}
        for r in vis:
            counts[r['status']] = counts.get(r['status'], 0) + 1
            m = matrix_d.setdefault(r['type'], {'type': r['type'], 'open': 0, 'progress': 0, 'solved': 0, 'overdue': 0, 'total': 0})
            m['total'] += 1
            if r['status'] in ('Resolved', 'Closed'):
                m['solved'] += 1
            elif r['status'] == 'In Progress':
                m['progress'] += 1
            else:
                m['open'] += 1
            if r['due_at'] and r['due_at'] < nows and (r['status'] not in ('Resolved', 'Closed')):
                m['overdue'] += 1
        progress = counts.get('In Progress', 0)
        solved = counts.get('Resolved', 0) + counts.get('Closed', 0)
        open_count = total - solved
        open_only = total - solved - progress
        overdue = sum((m['overdue'] for m in matrix_d.values()))
        within_sla = max(total - overdue, 0)
        sla_pct = round(within_sla / total * 100 if total else 100)
        matrix = sorted(matrix_d.values(), key=lambda m: -m['total'])
        recent = c.execute(f'SELECT t.*,s.name service,u.full_name assignee FROM tickets t LEFT JOIN services s ON s.id=t.service_id LEFT JOIN users u ON u.id=t.assignee_id WHERE {vsql} ORDER BY t.id DESC LIMIT 8', vargs).fetchall()
        services = c.execute("SELECT s.*,u.full_name owner,(SELECT count(*) FROM tickets t WHERE t.service_id=s.id AND t.status NOT IN ('Resolved','Closed')) open_count FROM services s LEFT JOIN users u ON u.id=s.owner_id WHERE s.is_main=1 ORDER BY s.id").fetchall()
        map_services = services
        cats = [{'type': m['type'], 'n': m['total']} for m in matrix]
        workload = runtime.workload_rows(c, u_, 8)
        asset_scope, asset_args = runtime.asset_scope_sql(u_, runtime.ORG, c)
        asset_count = c.execute('SELECT count(*) n FROM assets a WHERE ' + asset_scope, asset_args).fetchone()['n']
        services = runtime.scoped_service_counts(c, services)
        map_services = services
        activity = c.execute('SELECT tl.* FROM timeline tl JOIN tickets t ON t.id=tl.ticket_id WHERE ' + vsql + ' ORDER BY tl.id DESC LIMIT 7', vargs).fetchall()
        catvals = [r['n'] for r in cats[:3]] + [0, 0, 0]
        cat_pct = [round(catvals[i] / total * 100) if total else 0 for i in range(3)]
        trend = []
        for days in range(6, -1, -1):
            d = runtime.datetime.now() - runtime.timedelta(days=days)
            ds = d.strftime('%Y-%m-%d')
            m = {}
            for r_ in vis:
                if (r_['created_at'] or '')[:10] == ds:
                    m[r_['status']] = m.get(r_['status'], 0) + 1
            trend.append({'label': d.strftime('%d %b'), 'open': m.get('Open', 0) + m.get('New', 0), 'progress': m.get('In Progress', 0), 'closed': m.get('Resolved', 0) + m.get('Closed', 0), 'total': sum(m.values())})
        for t in recent:
            pass
        recent2 = []
        for t in recent:
            x = dict(t)
            x['sla'] = '—'
            if x.get('due_at'):
                try:
                    delta = runtime.datetime.strptime(x['due_at'][:19], '%Y-%m-%d %H:%M:%S') - runtime.datetime.now()
                    x['sla'] = 'Vonuar' if delta.total_seconds() < 0 and x['status'] not in ('Resolved', 'Closed') else f'{max(0, int(delta.total_seconds() // 3600))}h'
                except:
                    x['sla'] = '—'
            recent2.append(x)
        ts = runtime.space_summary_(c, u_)
        c.close()
        return runtime.render_template('dashboard.html', teams=ts, total=total, counts=counts, open_count=open_count, progress=progress, solved=solved, overdue=overdue, within_sla=within_sla, sla_pct=sla_pct, recent=recent2, services=services, map_services=map_services, cats=cats, cat_pct=cat_pct, workload=workload, activity=activity, trend=trend, asset_count=asset_count, open_only=open_only, matrix=matrix)
    runtime.dashboard = dashboard

    @runtime.login_required
    def tickets():
        q = runtime.request.args.get('q', '').strip()
        typ = runtime.request.args.get('type', '').strip()
        mine = runtime.request.args.get('mine', '').strip()
        st = runtime.request.args.get('status', '').strip()
        if typ not in runtime.TYPES:
            typ = ''
        if st not in ('open', 'closed', 'opened', 'progress', 'done', 'overdue') and st not in runtime.TRANS:
            st = ''
        grp = 'type' if runtime.request.args.get('group') == 'type' else ''
        u = runtime.current()
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(u)
        cond = [vsql]
        args = list(vargs)
        if q:
            cond.append('(t.code LIKE ? OR t.title LIKE ? OR t.description LIKE ? OR s.name LIKE ? OR u.full_name LIKE ?)')
            args += ['%' + q + '%'] * 5
        if typ:
            cond.append('t.type=?')
            args.append(typ)
        if mine:
            cond.append(runtime.mine_sql()[0])
            args += [u['id']] * 5
        if st == 'open':
            cond.append("t.status NOT IN ('Resolved','Closed')")
        elif st in ('closed', 'done'):
            cond.append("t.status IN ('Resolved','Closed')")
        elif st == 'opened':
            cond.append("t.status IN ('Open','New','Assigned','Waiting')")
        elif st == 'progress':
            cond.append("t.status='In Progress'")
        elif st == 'overdue':
            cond.append("t.due_at IS NOT NULL AND t.due_at<? AND t.status NOT IN ('Resolved','Closed')")
            args.append(runtime.now())
        elif st:
            cond.append('t.status=?')
            args.append(st)
        sql = 'SELECT t.*,s.name service,u.full_name assignee,rq.full_name requester FROM tickets t LEFT JOIN services s ON s.id=t.service_id LEFT JOIN users u ON u.id=t.assignee_id LEFT JOIN users rq ON rq.id=t.requester_id WHERE ' + ' AND '.join(cond) + (' ORDER BY t.type, t.id DESC LIMIT 500' if grp else ' ORDER BY t.id DESC LIMIT 500')
        rows = c.execute(sql, args).fetchall()
        c.close()
        tc = {}
        for r in rows:
            tc[r['type']] = tc.get(r['type'], 0) + 1
        title = 'My tickets' if mine and (not typ) else runtime.TYPE_TITLES.get(typ, typ) + (' – mine' if mine else '') if typ else 'Monitoring & Operations – all tickets'
        return runtime.render_template('tickets.html', tickets=rows, q=q, typ=typ, mine=mine, st=st, grp=grp, type_counts=tc, title=title, statuses=list(runtime.TRANS))
    runtime.tickets = tickets

    @runtime.login_required
    def tasks_view():
        u = runtime.current()
        uid = u['id']
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(u)
        scope = runtime.request.args.get('scope', 'mine')
        scope = scope if scope in ('mine', 'all') else 'mine'
        st = runtime.request.args.get('status', 'open')
        st = st if st in ('open', 'done', 'all') else 'open'
        items = []
        cond = [vsql]
        args = list(vargs)
        if scope == 'mine':
            cond.append('EXISTS(SELECT 1 FROM task_assignees xm WHERE xm.task_id=ta.id AND xm.user_id=?)')
            args.append(uid)
        if st == 'open':
            cond.append("ta.status!='Completed'")
        elif st == 'done':
            cond.append("ta.status='Completed'")
        for r in c.execute("SELECT ta.*,t.code,t.title ticket_title,t.status ticket_status,g.name group_name,(SELECT group_concat(u.full_name, ', ') FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=ta.id) assignees,EXISTS(SELECT 1 FROM task_assignees xm WHERE xm.task_id=ta.id AND xm.user_id=?) is_mine FROM tasks ta JOIN tickets t ON t.id=ta.ticket_id LEFT JOIN support_groups g ON g.id=ta.group_id WHERE " + ' AND '.join(cond) + ' ORDER BY ta.due_at IS NULL,ta.due_at LIMIT 300', [uid] + args):
            items.append(dict(kind='Task', url=runtime.url_for('task_detail', taskid=r['id']), parent=bool(r['parent_id']), id=r['id'], ticket_id=r['ticket_id'], title=r['title'], desc=r['description'], code=r['code'], ticket_title=r['ticket_title'], group=r['group_name'], assignees=r['assignees'], priority=r['priority'], status=r['status'], due=(r['due_at'] or '').replace('T', ' ')[:16], done=r['status'] == 'Completed', notes=r['completion_notes'], can_complete=r['status'] != 'Completed' and (bool(r['is_mine']) or u['role'] in runtime.WRITE), done_cfg={'action': runtime.url_for('complete_task', taskid=r['id']), 'title': 'Complete task: ' + (r['title'] or '')}))
        cond = ['t.type=?', vsql]
        args = ['Task'] + list(vargs)
        if scope == 'mine':
            cond.append(runtime.mine_sql()[0])
            args += [uid] * 5
        if st == 'open':
            cond.append("t.status NOT IN ('Resolved','Closed')")
        elif st == 'done':
            cond.append("t.status IN ('Resolved','Closed')")
        for r in c.execute('SELECT t.*,u.full_name assignee FROM tickets t LEFT JOIN users u ON u.id=t.assignee_id WHERE ' + ' AND '.join(cond) + ' ORDER BY t.due_at IS NULL,t.due_at LIMIT 300', args):
            items.append(dict(kind='Task (ticket)', url=runtime.url_for('ticket_detail', tid=r['id']), parent=False, id=r['id'], ticket_id=r['id'], title=r['title'], desc=r['description'], code=r['code'], ticket_title='', group=r['structure'], assignees=r['assignee'], priority=r['priority'], status=r['status'], due=(r['due_at'] or '')[:16], done=r['status'] in ('Resolved', 'Closed'), notes=r['resolution_note'] or '', can_complete=r['status'] not in ('Resolved', 'Closed') and runtime.can_write(c, r), done_cfg={'action': runtime.url_for('ticket_detail', tid=r['id']), 'title': 'Complete: ' + (r['title'] or ''), 'fields': {'action': 'status', 'status': 'Resolved'}}))
        c.close()
        items.sort(key=lambda x: (x['done'], x['due'] or '9999', x['code'] or ''))
        return runtime.render_template('tasks.html', items=items, scope=scope, st=st, now_str=runtime.now()[:16])
    runtime.tasks_view = tasks_view

    @runtime.login_required
    def calendar():
        try:
            offset = int(runtime.request.args.get('offset', 0))
        except ValueError:
            offset = 0
        offset = max(-120, min(120, offset))
        sel = runtime.request.args.get('user', '').strip()
        sel = int(sel) if sel.isdigit() else 0
        base = runtime.datetime.now().replace(day=1)
        month = (base.month - 1 + offset) % 12 + 1
        year = base.year + (base.month - 1 + offset) // 12
        first = runtime.datetime(year, month, 1)
        start = (first - runtime.timedelta(days=first.weekday())).date()
        end = start + runtime.timedelta(days=41)
        u = runtime.current()
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(u)
        evs = []

        def add(kind, uid, uname, code, title, link, s0, e0, status, prio, extra):
            if not e0:
                return
            s0 = s0 or e0
            if e0 < s0:
                e0 = s0
            if e0 < start or s0 > end or (sel and (uid or 0) != sel):
                return
            evs.append(dict(kind=kind, uid=uid or 0, uname=uname or 'Unassigned', code=code, title=title, link=link, s=s0, e=e0, done=status in ('Resolved', 'Closed', 'Completed'), prio=prio, extra=extra, color=runtime.PALETTE[uid % len(runtime.PALETTE)] if uid else '#7a8794'))
        for t in c.execute(f'SELECT t.*,us.full_name uname FROM tickets t LEFT JOIN users us ON us.id=t.assignee_id WHERE t.due_at IS NOT NULL AND {vsql} AND t.due_at>=? AND substr(t.created_at,1,10)<=?', list(vargs) + [str(start), str(end)]):
            ds = runtime.pdt(t['due_at'])
            cs = runtime.pdt(t['created_at'])
            add('ticket', t['assignee_id'], t['uname'], t['code'], t['title'], runtime.url_for('ticket_detail', tid=t['id']), cs.date() if cs else None, ds.date() if ds else None, t['status'], t['priority'], 'Due date: ' + str(t['due_at'])[:16])
        for t in c.execute(f'SELECT ta.*,t.code,x.user_id uid,uu.full_name uname FROM tasks ta JOIN tickets t ON t.id=ta.ticket_id JOIN task_assignees x ON x.task_id=ta.id JOIN users uu ON uu.id=x.user_id WHERE ta.due_at IS NOT NULL AND {vsql} AND ta.due_at>=? AND substr(ta.created_at,1,10)<=?', list(vargs) + [str(start), str(end)]):
            ds = runtime.pdt(t['due_at'])
            cs = runtime.pdt(t['created_at'])
            add('task', t['uid'], t['uname'], t['code'], t['title'], runtime.url_for('task_detail', taskid=t['id']), cs.date() if cs else None, ds.date() if ds else None, t['status'], t['priority'], 'Due date: ' + str(t['due_at']).replace('T', ' ')[:16])
        people = runtime.visible_users(c, c.execute('SELECT id,full_name FROM users WHERE active=1 ORDER BY full_name').fetchall())
        c.close()
        weeks = []
        today = runtime.datetime.now().date()
        for w in range(6):
            ws = start + runtime.timedelta(days=7 * w)
            we = ws + runtime.timedelta(days=6)
            days = []
            for i in range(7):
                d = ws + runtime.timedelta(days=i)
                days.append({'day': d.day, 'current': d.month == month, 'we': i >= 5, 'today': d == today})
            segs = []
            for e in evs:
                if e['e'] < ws or e['s'] > we:
                    continue
                segs.append(dict(e=e, c1=(max(e['s'], ws) - ws).days, c2=(min(e['e'], we) - ws).days, cl=e['s'] < ws, cr=e['e'] > we))
            segs.sort(key=lambda x: (x['c1'], -(x['c2'] - x['c1']), x['e']['code'] or ''))
            lanes = []
            for sg in segs:
                for li, last in enumerate(lanes):
                    if last < sg['c1']:
                        lanes[li] = sg['c2']
                        sg['lane'] = li
                        break
                else:
                    lanes.append(sg['c2'])
                    sg['lane'] = len(lanes) - 1
            weeks.append(dict(days=days, bars=segs, h=max(100, 34 + len(lanes) * 24 + 8)))
        legend = {}
        for e in evs:
            legend[e['uid']] = (e['uname'], e['color'])
        legend = sorted(legend.values())
        names = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        return runtime.render_template('calendar.html', weeks=weeks, legend=legend, people=people, sel=sel, month_name=names[month - 1], year=year, offset=offset, count=len(evs))
    runtime.calendar = calendar

    def _rep_filters():
        f = {k: (runtime.request.args.get(k) or '').strip() for k in ('date_from', 'date_to', 'type', 'status')}
        for k in ('date_from', 'date_to'):
            if f[k]:
                try:
                    runtime.datetime.strptime(f[k], '%Y-%m-%d')
                except ValueError:
                    runtime.abort(400)
        if f['type'] and f['type'] not in runtime.TYPES:
            runtime.abort(400)
        if f['status'] and f['status'] not in runtime.TRANS:
            runtime.abort(400)
        return f
    runtime._rep_filters = _rep_filters

    def _csv_safe(v):
        if v is None:
            return ''
        if isinstance(v, str) and (v[:1] in ('=', '+', '-', '@', '\t', '\r', '\n') or v.lstrip(' \t\r\n')[:1] in ('=', '+', '-', '@')):
            return "'" + v
        return v
    runtime._csv_safe = _csv_safe

    def _sla_label(t):
        due = runtime.pdt(t['due_at'])
        if not due:
            return '-'
        end = runtime.pdt(t['resolved_at'] or t['closed_at']) or (runtime.datetime.now() if t['status'] not in ('Resolved', 'Closed') else None)
        if not end:
            return '-'
        return 'Within deadline' if end <= due else 'Past due'
    runtime._sla_label = _sla_label

    def export_tickets(fl):
        u = runtime.current()
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(u)
        cond = [vsql]
        args = list(vargs)
        if fl['date_from']:
            cond.append('substr(t.created_at,1,10)>=?')
            args.append(fl['date_from'])
        if fl['date_to']:
            cond.append('substr(t.created_at,1,10)<=?')
            args.append(fl['date_to'])
        if fl['type']:
            cond.append('t.type=?')
            args.append(fl['type'])
        if fl['status']:
            cond.append('t.status=?')
            args.append(fl['status'])
        rows = c.execute('SELECT t.*,s.name service,rq.full_name requester,asg.full_name assignee FROM tickets t LEFT JOIN services s ON s.id=t.service_id LEFT JOIN users rq ON rq.id=t.requester_id LEFT JOIN users asg ON asg.id=t.assignee_id WHERE ' + ' AND '.join(cond) + ' ORDER BY t.id DESC', args).fetchall()
        c.close()
        hdr = ['Code', 'Type', 'Title', 'Category', 'Service', 'Structure', 'Prioriteti', 'Statusi', 'Requester', 'Assignee', 'Created', 'Due date (SLA)', 'Resolved', 'Closed', 'SLA']
        return (hdr, [[r['code'], r['type'], r['title'], r['category'], r['service'], r['structure'], r['priority'], r['status'], r['requester'], r['assignee'], r['created_at'], r['due_at'], r['resolved_at'], r['closed_at'], runtime._sla_label(r)] for r in rows])
    runtime.export_tickets = export_tickets

    def export_tasks(fl):
        u = runtime.current()
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(u)
        cond = [vsql]
        args = list(vargs)
        if fl['date_from']:
            cond.append('substr(ta.created_at,1,10)>=?')
            args.append(fl['date_from'])
        if fl['date_to']:
            cond.append('substr(ta.created_at,1,10)<=?')
            args.append(fl['date_to'])
        if fl['type']:
            cond.append('t.type=?')
            args.append(fl['type'])
        if fl['status']:
            cond.append('t.status=?')
            args.append(fl['status'])
        rows = c.execute("SELECT ta.*,t.code,t.title ticket_title,g.name group_name,(SELECT group_concat(u.full_name, ', ') FROM task_assignees x JOIN users u ON u.id=x.user_id WHERE x.task_id=ta.id) assignees FROM tasks ta JOIN tickets t ON t.id=ta.ticket_id LEFT JOIN support_groups g ON g.id=ta.group_id WHERE " + ' AND '.join(cond) + ' ORDER BY ta.id DESC', args).fetchall()
        c.close()
        hdr = ['Ticket', 'Ticket title', 'Tasks', 'Description', 'Sektori/Grupi', 'Users', 'Prioriteti', 'Statusi', 'Created', 'Due date', 'Completed', 'Completion notes']
        return (hdr, [[r['code'], r['ticket_title'], r['title'], r['description'], r['group_name'], r['assignees'], r['priority'], r['status'], r['created_at'], (r['due_at'] or '').replace('T', ' '), r['completed_at'], r['completion_notes']] for r in rows])
    runtime.export_tasks = export_tasks

    def export_summary(fl):
        hdr, tk = runtime.export_tickets(fl)
        out = [['Summary', 'Total tickets', len(tk)]]
        for k, i in (('By status', 7), ('By type', 1), ('By priority', 6), ('By SLA', 14), ('By assignee', 9)):
            cnt = {}
            for r in tk:
                cnt[r[i] or '-'] = cnt.get(r[i] or '-', 0) + 1
            out += [[k, a, b] for a, b in sorted(cnt.items(), key=lambda x: -x[1])]
        return (['Seksioni', 'Treguesi', 'Vlera'], out)
    runtime.export_summary = export_summary
    runtime.EXPORTERS = {'tickets': runtime.export_tickets, 'tasks': runtime.export_tasks, 'summary': runtime.export_summary}

    def _col(n):
        s = ''
        n += 1
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
    runtime._col = _col

    def make_xlsx(headers, rows, sheet='Raport'):
        from xml.sax.saxutils import escape
        bad = runtime.re.compile('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]')

        def cell(r, ci, v, st):
            ref = f'{runtime._col(ci)}{r}'
            if isinstance(v, (int, float)) and (not isinstance(v, bool)):
                return f'<c r="{ref}" s="{st}"><v>{v}</v></c>'
            return f'''<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{escape(bad.sub('', str(v if v is not None else '')))}</t></is></c>'''
        widths = [min(max([len(str(h))] + [len(str(r[i])) if r[i] is not None else 0 for r in rows[:300]]) + 3, 60) for i, h in enumerate(headers)]
        sd = ''.join((f'<row r="{ri}">' + ''.join((cell(ri, ci, v, 1 if ri == 1 else 0) for ci, v in enumerate(row))) + '</row>' for ri, row in enumerate([headers] + rows, 1)))
        cols = ''.join((f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)))
        ws = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>{sd}</sheetData><autoFilter ref="A1:{runtime._col(len(headers) - 1)}{len(rows) + 1}"/></worksheet>'
        styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0B4F8A"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
        sn = escape(runtime.re.sub('[\\[\\]:*?/\\\\]', '', sheet))[:31]
        buf = runtime.io.BytesIO()
        with runtime.zipfile.ZipFile(buf, 'w', runtime.zipfile.ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
            z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            z.writestr('xl/workbook.xml', f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{sn}" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
            z.writestr('xl/styles.xml', styles)
            z.writestr('xl/worksheets/sheet1.xml', ws)
        return buf.getvalue()
    runtime.make_xlsx = make_xlsx

    @runtime.login_required
    def reports():
        c = runtime.db()
        vsql, vargs = runtime.vis_ticket_sql(runtime.current(), 't')
        VT = f'(SELECT t.id FROM tickets t WHERE {vsql})'
        total = c.execute(f'SELECT count(*) n FROM tickets t WHERE {vsql}', vargs).fetchone()['n']
        open_n = c.execute(f"SELECT count(*) n FROM tickets t WHERE {vsql} AND t.status NOT IN ('Resolved','Closed')", vargs).fetchone()['n']
        overdue = c.execute(f"SELECT count(*) n FROM tickets t WHERE {vsql} AND t.due_at IS NOT NULL AND t.due_at<? AND t.status NOT IN ('Resolved','Closed')", list(vargs) + [runtime.now()]).fetchone()['n']
        tasks = c.execute(f'SELECT count(*) n FROM tasks WHERE ticket_id IN {VT}', vargs).fetchone()['n']
        done = c.execute(f"SELECT count(*) n FROM tasks WHERE status='Completed' AND ticket_id IN {VT}", vargs).fetchone()['n']
        statuses = []
        for r in c.execute(f'SELECT t.status,count(*) n FROM tickets t WHERE {vsql} GROUP BY t.status ORDER BY n DESC', vargs):
            statuses.append({'status': r['status'], 'n': r['n'], 'pct': round(r['n'] / total * 100) if total else 0})
        workload = runtime.workload_rows(c, runtime.current())
        kpis = [{'label': 'Ticket Total', 'value': total, 'note': 'All tickets'}, {'label': 'Active backlog', 'value': open_n, 'note': 'Unresolved / open'}, {'label': 'SLA overdue', 'value': overdue, 'note': 'Past due'}, {'label': 'Task Completion', 'value': f'{(round(done / tasks * 100) if tasks else 0)}%', 'note': f'{done}/{tasks} task'}]
        c.close()
        return runtime.render_template('reports.html', reports=kpis, statuses=statuses, workload=workload, fl=runtime._rep_filters(), types=runtime.TYPES, status_list=list(runtime.TRANS))
    runtime.reports = reports

    @runtime.login_required
    def export_report(kind, fmt):
        if kind not in runtime.EXPORTERS or fmt not in ('csv', 'xlsx'):
            return ('Not found', 404)
        hdr, rows = runtime.EXPORTERS[kind](runtime._rep_filters())
        runtime.audit('Export', 'Report', 0, new=f'{kind}.{fmt} ({len(rows)} rows)')
        name = f'OpenITSM_{kind}_{runtime.datetime.now():%Y%m%d_%H%M}.{fmt}'
        h = {'Content-Disposition': f'attachment; filename="{name}"'}
        if fmt == 'xlsx':
            return runtime.Response(runtime.make_xlsx(hdr, rows, {'tickets': 'Ticket-et', 'tasks': 'Tasks', 'summary': 'Summary'}[kind]), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=h)
        buf = runtime.io.StringIO()
        w = runtime.csv.writer(buf, delimiter=';')
        w.writerow(hdr)
        for r in rows:
            w.writerow([runtime._csv_safe(v) for v in r])
        return runtime.Response('\ufeff' + buf.getvalue(), mimetype='text/csv; charset=utf-8', headers=h)
    runtime.export_report = export_report

    @runtime.login_required
    def notifications():
        c = runtime.db()
        rows = c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC', (runtime.session['uid'],)).fetchall()
        c.close()
        return runtime.render_template('notifications.html', notifications=rows)
    runtime.notifications = notifications

    @runtime.login_required
    def api_poll():
        try:
            since = int(runtime.request.args.get('since', 0))
        except ValueError:
            since = 0
        c = runtime.db()
        rows = c.execute('SELECT id,title,message,link,kind FROM notifications WHERE user_id=? AND id>? ORDER BY id LIMIT 10', (runtime.session['uid'], since)).fetchall()
        n = c.execute('SELECT count(*) n FROM notifications WHERE user_id=? AND is_read=0', (runtime.session['uid'],)).fetchone()['n']
        c.close()
        return runtime.jsonify(unread=n, last=max([r['id'] for r in rows], default=since), items=[dict(r) for r in rows])
    runtime.api_poll = api_poll

    def audit_scope(c):
        if runtime.current()['role'] == 'System Administrator':
            return ('1=1', [])
        ids = runtime.ORG.scope_ids(c, runtime.current())
        if not ids:
            return ('0=1', [])
        marks = ','.join(('?' for _ in ids))
        clauses = []
        args = []
        for kind, query in (('User', 'SELECT id FROM users WHERE org_unit_id IN (' + marks + ')'), ('Ticket', 'SELECT id FROM tickets WHERE unit_id IN (' + marks + ')'), ('Task', 'SELECT ta.id FROM tasks ta JOIN tickets t ON t.id=ta.ticket_id WHERE t.unit_id IN (' + marks + ')'), ('Asset', 'SELECT id FROM assets WHERE unit_id IN (' + marks + ')'), ('Service', 'SELECT id FROM services WHERE unit_id IN (' + marks + ')')):
            clauses.append('(a.object_type=? AND a.object_id IN (' + query + '))')
            args.extend([kind, *ids])
        return ('(' + ' OR '.join(clauses) + ')', args)
    runtime.audit_scope = audit_scope

    def _audit_query(args, limit, offset=0):
        f = {k: (args.get(k) or '').strip() for k in ('date_from', 'date_to', 'actor', 'action', 'obj', 'q')}
        for k in ('date_from', 'date_to'):
            if f[k]:
                try:
                    runtime.datetime.strptime(f[k], '%Y-%m-%d')
                except ValueError:
                    runtime.abort(400)
        for key in ('date_from', 'date_to'):
            if f[key]:
                try:
                    runtime.datetime.strptime(f[key], '%Y-%m-%d')
                except ValueError:
                    runtime.abort(400)
        if f['actor'] and f['actor'] != 'none' and (not f['actor'].isascii() or not f['actor'].isdigit() or int(f['actor']) <= 0):
            runtime.abort(400)
        cond = ['1=1']
        a = []
        if f['date_from']:
            cond.append('substr(a.created_at,1,10)>=?')
            a.append(f['date_from'])
        if f['date_to']:
            cond.append('substr(a.created_at,1,10)<=?')
            a.append(f['date_to'])
        if f['actor'].isdigit():
            cond.append('a.actor_id=?')
            a.append(int(f['actor']))
        elif f['actor'] == 'none':
            cond.append('a.actor_id IS NULL')
        if f['action']:
            cond.append('a.action=?')
            a.append(f['action'])
        if f['obj']:
            cond.append('a.object_type=?')
            a.append(f['obj'])
        if f['q']:
            cond.append('(a.old_value LIKE ? OR a.new_value LIKE ? OR a.ip LIKE ? OR u.full_name LIKE ? OR u.username LIKE ? OR CAST(a.object_id AS TEXT)=?)')
            a += ['%' + f['q'] + '%'] * 5 + [f['q']]
        c = runtime.db()
        scoped, scoped_args = runtime.audit_scope(c)
        cond.append(scoped)
        a.extend(scoped_args)
        where = ' AND '.join(cond)
        total = c.execute(f'SELECT count(*) n FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE {where}', a).fetchone()['n']
        rows = c.execute(f'SELECT a.*,u.full_name,u.username FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE {where} ORDER BY a.id DESC LIMIT ? OFFSET ?', a + [limit, offset]).fetchall()
        c.close()
        return (f, rows, total)
    runtime._audit_query = _audit_query

    def _audit_guard():
        if not (runtime.ORG.can_audit(runtime.current()) if runtime.ORG else runtime.current()['role'] in runtime.AUDIT_ROLES):
            runtime.audit('AccessDenied', 'Audit', 0)
            return ('Access Denied', 403)
    runtime._audit_guard = _audit_guard

    @runtime.login_required
    def audit_view():
        g_ = runtime._audit_guard()
        if g_:
            return g_
        try:
            page = max(1, int(runtime.request.args.get('page', 1)))
        except ValueError:
            page = 1
        per = 100
        f, rows, total = runtime._audit_query(runtime.request.args, per, (page - 1) * per)
        c = runtime.db()
        scoped, args = runtime.audit_scope(c)
        visible = c.execute('SELECT a.* FROM audit a WHERE ' + scoped, args).fetchall()
        actions = sorted({r['action'] for r in visible})
        objs = sorted({r['object_type'] for r in visible})
        us, ua = runtime.directory_scope_sql(runtime.current(), runtime.ORG, c)
        users = c.execute('SELECT u.id,u.full_name,u.username FROM users u WHERE ' + us + ' ORDER BY u.full_name', ua).fetchall()
        since = (runtime.datetime.now() - runtime.timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        recent = [r for r in visible if r['created_at'] and r['created_at'] >= since]
        st = dict(all=len(visible), h24=len(recent), denied=sum((r['action'] == 'AccessDenied' for r in recent)), failed=sum((r['action'] == 'LoginFailed' for r in recent)))
        c.close()
        qs = {k: v for k, v in f.items() if v}
        return runtime.render_template('audit.html', rows=rows, f=f, total=total, page=page, pages=max(1, (total + per - 1) // per), per=per, actions=actions, objs=objs, users=users, st=st, qs=qs)
    runtime.audit_view = audit_view

    @runtime.login_required
    def audit_export(fmt):
        g_ = runtime._audit_guard()
        if g_:
            return g_
        if fmt not in ('csv', 'xlsx'):
            return ('Not found', 404)
        f, rows, total = runtime._audit_query(runtime.request.args, 20000, 0)
        runtime.audit('AuditExport', 'Audit', 0, new=f'{fmt}, {len(rows)} rows')
        hdr = ['ID', 'Time', 'User', 'Username', 'Action', 'Object', 'Object ID', 'Old value', 'New value', 'IP']
        data = [[r['id'], r['created_at'], r['full_name'] or ('(system/anonymous)' if not r['actor_id'] else f"#{r['actor_id']}"), r['username'] or '', r['action'], r['object_type'], r['object_id'], r['old_value'], r['new_value'], r['ip']] for r in rows]
        name = f'OpenITSM_audit_{runtime.datetime.now():%Y%m%d_%H%M}.{fmt}'
        h = {'Content-Disposition': f'attachment; filename="{name}"'}
        if fmt == 'xlsx':
            return runtime.Response(runtime.make_xlsx(hdr, data, 'Audit Log'), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=h)
        buf = runtime.io.StringIO()
        w = runtime.csv.writer(buf, delimiter=';')
        w.writerow(hdr)
        for r in data:
            w.writerow([runtime._csv_safe(v) for v in r])
        return runtime.Response('\ufeff' + buf.getvalue(), mimetype='text/csv; charset=utf-8', headers=h)
    runtime.audit_export = audit_export
