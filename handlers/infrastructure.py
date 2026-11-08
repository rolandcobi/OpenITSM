"""P1-05 infrastructure family. Pure import; instance dependencies are explicit."""

def register(runtime):

    @runtime.login_required
    def assets():
        c = runtime.db()
        me = runtime.current()
        scope, args = runtime.asset_scope_sql(me, runtime.ORG, c)
        can_edit = (me['role'] in runtime.ASSET_ROLES or bool(me['can_infra'])) and me['role'] != 'Auditor'

        def denied(status=403):
            c.close()
            return ('Access denied' if status == 403 else 'Invalid asset request', status)
        if runtime.request.method == 'POST':
            if not can_edit or scope == '0=1':
                return denied()
            f = runtime.request.form
            if any((len(f.getlist(k)) > 1 for k in ('asset_id', 'unit_id', 'owner_id', 'service_id', 'action'))):
                return denied(400)
            action = f.get('action', 'create')
            if action not in ('create', 'update', 'delete'):
                return denied(400)
            old = None
            if action in ('update', 'delete'):
                aid = f.get('asset_id', '')
                if not aid.isascii() or not aid.isdigit() or int(aid) <= 0:
                    return denied(400)
                old = c.execute('SELECT a.* FROM assets a WHERE a.id=? AND ' + scope, [int(aid), *args]).fetchone()
                if not old:
                    return denied()
            if action == 'delete':
                if f.get('confirm'):
                    c.execute('DELETE FROM assets WHERE id=?', (old['id'],))
                    c.commit()
                    c.close()
                    runtime.audit('Delete', 'Asset', old['id'], old['name'])
                    return runtime.redirect(runtime.url_for('assets'))
                c.close()
                return runtime.redirect(runtime.url_for('assets'))
            name = f.get('name', '').strip()
            if not name:
                return denied(400)
            selected = {}
            units = []
            for field, table, column in (('owner_id', 'users', 'org_unit_id'), ('service_id', 'services', 'unit_id')):
                value = f.get(field, '')
                if value and (not value.isascii() or not value.isdigit() or int(value) <= 0):
                    return denied(400)
                selected[field] = int(value) if value else None
                if value:
                    record = c.execute('SELECT * FROM ' + table + ' WHERE id=?' + (' AND active=1' if table == 'users' else ''), (int(value),)).fetchone()
                    if not record:
                        return denied(400)
                    if field == 'service_id':
                        service_scope, service_args = runtime.service_read_scope_sql(me, runtime.ORG, c)
                        if not c.execute('SELECT 1 FROM services s WHERE s.id=? AND ' + service_scope, [int(value), *service_args]).fetchone():
                            return denied()
                    unit = record[column]
                    if unit is not None:
                        units.append(unit)
                    if me['role'] != 'System Administrator' and (unit is None and field == 'owner_id' or (unit is not None and unit not in args)):
                        return denied()
            raw = f.get('unit_id', '')
            if raw and (not raw.isascii() or not raw.isdigit() or int(raw) <= 0):
                return denied(400)
            unit = int(raw) if raw else old['unit_id'] if old and old['unit_id'] is not None else units[0] if units else me['org_unit_id']
            if unit is not None and (not c.execute('SELECT 1 FROM org_units WHERE id=?', (unit,)).fetchone()):
                return denied(400)
            if any((linked != unit for linked in units)):
                return denied(400)
            if me['role'] != 'System Administrator' and unit not in args:
                return denied()
            values = (name, f.get('asset_type', ''), f.get('hostname', ''), f.get('ip_address', ''), selected['service_id'], f.get('structure', ''), f.get('location', ''), selected['owner_id'], f.get('criticality', 'Medium'), f.get('status', 'Operational'), f.get('notes', ''), unit)
            if old:
                c.execute('UPDATE assets SET name=?,asset_type=?,hostname=?,ip_address=?,service_id=?,structure=?,location=?,owner_id=?,criticality=?,status=?,notes=?,unit_id=? WHERE id=?', (*values, old['id']))
                aid = old['id']
            else:
                aid = c.execute('INSERT INTO assets(name,asset_type,hostname,ip_address,service_id,structure,location,owner_id,criticality,status,notes,unit_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (*values, runtime.now())).lastrowid
            c.commit()
            c.close()
            runtime.audit('Update' if old else 'Create', 'Asset', aid, new=name)
            return runtime.redirect(runtime.url_for('assets'))
        rows = c.execute('SELECT a.*,s.name service,u.full_name owner FROM assets a LEFT JOIN services s ON s.id=a.service_id LEFT JOIN users u ON u.id=a.owner_id WHERE ' + scope + ' ORDER BY a.id DESC', args).fetchall()
        if me['role'] == 'System Administrator':
            services = c.execute('SELECT * FROM services ORDER BY name').fetchall()
            users = c.execute('SELECT * FROM users WHERE active=1 ORDER BY full_name').fetchall()
        else:
            marks = ','.join(('?' for _ in args)) or 'NULL'
            services = c.execute('SELECT * FROM services WHERE unit_id IS NULL OR unit_id IN (' + marks + ') ORDER BY name', args).fetchall()
            users = c.execute('SELECT * FROM users WHERE active=1 AND org_unit_id IN (' + marks + ') ORDER BY full_name', args).fetchall()
        services = runtime.visible_services(c, services)
        unit_options = [o for o in runtime.ORG.options(c) if me['role'] == 'System Administrator' or o['id'] in args]
        c.close()
        return runtime.render_template('assets.html', assets=rows, services=services, users=users, asset_unit_options=unit_options, can_edit=can_edit and scope != '0=1')
    runtime.assets = assets

    @runtime.login_required
    def services():
        c = runtime.db()
        me = c.execute('SELECT * FROM users WHERE id=?', (runtime.session['uid'],)).fetchone()
        can_sys = me['role'] == 'System Administrator' or (bool(me['can_infra']) and me['role'] != 'Auditor')
        if runtime.request.method == 'POST':
            f = runtime.request.form
            action = f.get('action') or 'update'
            if any((len(f.getlist(k)) > 1 for k in ('action', 'service_id', 'parent_service_id', 'unit_id', 'owner_id'))):
                c.close()
                return ('Invalid service request', 400)
            if action not in ('add_service', 'rename_service', 'add_subsection', 'update'):
                c.close()
                return ('Invalid service action', 400)
            if not can_sys and me['role'] != 'Service Owner':
                c.close()
                return ('Access denied', 403)
            scope, scope_args = runtime.service_write_scope_sql(me, runtime.ORG, c)
            service_unit = None
            if action == 'add_service':
                raw = f.get('unit_id', '')
                if raw and (not raw.isascii() or not raw.isdigit() or int(raw) <= 0):
                    c.close()
                    return ('Invalid unit', 400)
                service_unit = int(raw) if raw else me['org_unit_id']
                if service_unit is not None and (not c.execute('SELECT 1 FROM org_units WHERE id=?', (service_unit,)).fetchone()):
                    c.close()
                    return ('Invalid unit', 400)
                if me['role'] != 'System Administrator' and service_unit not in scope_args:
                    c.close()
                    return ('Access denied', 403)
            else:
                raw = f.get('parent_service_id' if action == 'add_subsection' else 'service_id', '')
                if not raw.isascii() or not raw.isdigit() or int(raw) <= 0:
                    c.close()
                    return ('Invalid service', 400)
                target = c.execute('SELECT s.* FROM services s WHERE s.id=? AND ' + scope, [int(raw), *scope_args]).fetchone()
                if not target:
                    c.close()
                    return ('Access denied', 403)
                service_unit = target['unit_id']
                if f.get('unit_id') and f['unit_id'] != str(service_unit):
                    c.close()
                    return ('Access denied', 403)
            owner = f.get('owner_id', '')
            if owner:
                if not owner.isascii() or not owner.isdigit() or int(owner) <= 0:
                    c.close()
                    return ('Invalid owner', 400)
                owner_row = c.execute('SELECT * FROM users WHERE id=? AND active=1', (int(owner),)).fetchone()
                if not owner_row:
                    c.close()
                    return ('Invalid owner', 400)
                if me['role'] != 'System Administrator' and owner_row['org_unit_id'] not in scope_args:
                    c.close()
                    return ('Access denied', 403)
            if action == 'add_service':
                if not can_sys:
                    c.close()
                    return ('Access denied', 403)
                name = runtime.request.form.get('name', '').strip()[:100]
                if not name:
                    c.close()
                    return ('Name required', 400)
                c.execute('INSERT INTO services(name,category,status,is_main,unit_id) VALUES(?,?,?,1,?)', (name, runtime.request.form.get('category', 'General')[:80], runtime.request.form.get('status', 'Operational'), service_unit))
                c.commit()
                c.close()
                return runtime.redirect(runtime.url_for('services'))
            if action == 'rename_service':
                sid = runtime.request.form.get('service_id', type=int)
                name = runtime.request.form.get('name', '').strip()[:100]
                if not can_sys:
                    c.close()
                    return ('Access denied', 403)
                if not sid or not name:
                    c.close()
                    return ('Invalid service', 400)
                c.execute('UPDATE services SET name=? WHERE id=?', (name, sid))
                c.commit()
                c.close()
                return runtime.redirect(runtime.url_for('services'))
            if runtime.request.form.get('action') == 'add_subsection':
                parent_id = int(runtime.request.form['parent_service_id'])
                parent = c.execute('SELECT * FROM services WHERE id=? AND is_main=1', (parent_id,)).fetchone()
                allowed = bool(parent) and (can_sys or (me['role'] == 'Service Owner' and parent['owner_id'] == me['id']))
                if not allowed:
                    c.close()
                    return ('Access denied', 403)
                c.execute('INSERT INTO services(name,category,status,owner_id,parent_service_id,is_main,unit_id) VALUES(?,?,?,?,?,0,?)', (runtime.request.form['name'].strip(), runtime.request.form.get('category', 'Subsection'), runtime.request.form.get('status', 'Operational'), runtime.request.form.get('owner_id') or None, parent_id, service_unit))
                c.commit()
                c.close()
                return runtime.redirect(runtime.url_for('services'))
            sid = int(runtime.request.form['service_id'])
            s = c.execute('SELECT * FROM services WHERE id=?', (sid,)).fetchone()
            allowed = bool(s) and (can_sys or (me['role'] == 'Service Owner' and s['owner_id'] == me['id']))
            if not allowed:
                c.close()
                return ('Access denied', 403)
            c.execute('UPDATE services SET status=?,owner_id=? WHERE id=?', (runtime.request.form['status'], runtime.request.form.get('owner_id') or None, sid))
            c.commit()
            runtime.audit('Update', 'Service', sid, s['status'], runtime.request.form['status'])
        rows = c.execute("SELECT s.*,u.full_name owner,(SELECT count(*) FROM tickets t WHERE t.service_id=s.id AND t.status NOT IN ('Resolved','Closed')) open_count,(SELECT count(*) FROM services ch WHERE ch.parent_service_id=s.id AND ch.is_main=0) subsection_count FROM services s LEFT JOIN users u ON u.id=s.owner_id WHERE s.is_main=1 ORDER BY s.id").fetchall()
        subsections = c.execute('SELECT ch.*,p.name parent_name,u.full_name owner FROM services ch JOIN services p ON p.id=ch.parent_service_id LEFT JOIN users u ON u.id=ch.owner_id WHERE ch.is_main=0 ORDER BY p.id,ch.name').fetchall()
        owners = c.execute("SELECT * FROM users WHERE role IN ('Service Owner','System Administrator') AND active=1 ORDER BY full_name").fetchall()
        rows = runtime.scoped_service_counts(c, rows)
        subsections = runtime.visible_services(c, subsections)
        user_scope, user_args = runtime.directory_scope_sql(me, runtime.ORG, c)
        owner_ids = {r[0] for r in c.execute('SELECT u.id FROM users u WHERE ' + user_scope, user_args)}
        owners = [r for r in owners if r['id'] in owner_ids]
        write_scope, write_args = runtime.service_write_scope_sql(me, runtime.ORG, c)
        editable_service_ids = {r[0] for r in c.execute('SELECT s.id FROM services s WHERE ' + write_scope, write_args)}
        c.close()
        return runtime.render_template('services.html', services=rows, subsections=subsections, owners=owners, can_sys=can_sys, me=me, editable_service_ids=editable_service_ids)
    runtime.services = services
