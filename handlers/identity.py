"""P1-05 identity family. Pure import; instance dependencies are explicit."""

def register(runtime):

    def login():
        if runtime.request.method == 'POST':
            un = runtime.request.form.get('username', '')[:64]
            ip = runtime.request.remote_addr or ''
            cutoff = runtime.time.time() - 300
            c = runtime.db()
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM login_attempts WHERE attempted_at<?', (cutoff,))
            failures = c.execute('SELECT count(*) FROM login_attempts WHERE ip=? AND attempted_at>=?', (ip, cutoff)).fetchone()[0]
            u = c.execute('SELECT * FROM users WHERE username=? AND active=1', (un,)).fetchone()
            if failures >= 20:
                c.close()
                runtime.flash('Too many attempts. Try again later.', 'danger')
                return (runtime.render_template('login.html'), 429)
            locked = bool(u and u['locked_until'] and (u['locked_until'] > runtime.now()))
            candidate = u['password_hash'] if u and isinstance(u['password_hash'], str) and u['password_hash'].startswith(('scrypt:', 'pbkdf2:')) else runtime.DUMMY_PASSWORD_HASH
            try:
                verified = runtime.check_password_hash(candidate, runtime.request.form.get('password', ''))
            except ValueError:
                verified = False
                runtime.check_password_hash(runtime.DUMMY_PASSWORD_HASH, runtime.request.form.get('password', ''))
            if u and (not locked) and (candidate != runtime.DUMMY_PASSWORD_HASH) and verified:
                c.execute('UPDATE users SET failed=0,locked_until=NULL WHERE id=?', (u['id'],))
                c.commit()
                c.close()
                runtime.session.clear()
                runtime.session.update(uid=u['id'], name=u['full_name'], role=u['role'], auth_version=u['auth_version'], issued_at=runtime.time.time())
                runtime.session['csrf'] = runtime.secrets.token_hex(16)
                runtime.session.permanent = True
                runtime.audit('Login', 'User', u['id'])
                runtime.session['popup'] = 1
                return runtime.redirect(runtime.url_for('profile') if not u['profile_done'] else runtime.url_for('dashboard'))
            c.execute('INSERT INTO login_attempts(ip,attempted_at) VALUES(?,?)', (ip, runtime.time.time()))
            if u and (not locked):
                n = (u['failed'] or 0) + 1
                lock = (runtime.datetime.now() + runtime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S') if n >= 5 else None
                c.execute('UPDATE users SET failed=?,locked_until=? WHERE id=?', (0 if lock else n, lock, u['id']))
                c.commit()
            c.commit()
            c.close()
            runtime.audit('LoginFailed', 'User', 0, new=un)
            runtime.flash('Invalid credentials.', 'danger')
        return runtime.render_template('login.html')
    runtime.login = login

    @runtime.login_required
    def logout():
        if runtime.request.method == 'GET':
            return runtime.render_template('logout.html')
        u = runtime.current()
        if u:
            c = runtime.db()
            c.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (u['id'],))
            c.commit()
            c.close()
        runtime.session.clear()
        return runtime.redirect(runtime.url_for('login'))
    runtime.logout = logout

    @runtime.login_required
    def notifications_read():
        c = runtime.db()
        c.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (runtime.current()['id'],))
        c.commit()
        c.close()
        return runtime.redirect(runtime.url_for('notifications'))
    runtime.notifications_read = notifications_read

    def pw_ok(pw, un=''):
        return len(pw) >= 12 and pw.lower() != un.lower()
    runtime.pw_ok = pw_ok

    def manager_required(f):

        @runtime.wraps(f)
        def w(*a, **k):
            if runtime.current()['role'] not in runtime.MANAGERS:
                runtime.audit('AccessDenied', 'Users', 0)
                return ('Access Denied', 403)
            return f(*a, **k)
        return w
    runtime.manager_required = manager_required

    @runtime.login_required
    def account():
        u = runtime.current()
        if runtime.request.method == 'POST':
            cur, new, conf = (runtime.request.form.get('current', ''), runtime.request.form.get('new', ''), runtime.request.form.get('confirm', ''))
            if not runtime.check_password_hash(u['password_hash'], cur):
                runtime.audit('PasswordChangeFailed', 'User', u['id'])
                runtime.flash('The current password is incorrect.', 'danger')
            elif new != conf:
                runtime.flash('The new passwords do not match.', 'danger')
            elif not runtime.pw_ok(new, u['username']):
                runtime.flash('The new password must contain at least 12 characters and differ from the username.', 'danger')
            elif runtime.check_password_hash(u['password_hash'], new):
                runtime.flash('The new password must differ from the current password.', 'danger')
            else:
                c = runtime.db()
                changed = c.execute('UPDATE users SET password_hash=?,must_change=0,auth_version=auth_version+1 WHERE id=? AND auth_version=?', (runtime.generate_password_hash(new), u['id'], u['auth_version'])).rowcount
                if changed != 1:
                    c.rollback()
                    c.close()
                    return ('Session changed; sign in again', 409)
                c.commit()
                c.close()
                runtime.audit('PasswordChange', 'User', u['id'])
                runtime.session['auth_version'] = u['auth_version'] + 1
                runtime.session['csrf'] = runtime.secrets.token_hex(16)
                runtime.flash('Password changed successfully.', 'success')
                return runtime.redirect(runtime.url_for('profile') if not u['profile_done'] else runtime.url_for('dashboard'))
        return runtime.render_template('account.html', u=u)
    runtime.account = account

    @runtime.login_required
    @runtime.manager_required
    def users_admin():
        me = runtime.current()
        c = runtime.db()
        sysadm = me['role'] == 'System Administrator'

        def back(msg, cat='danger'):
            c.close()
            runtime.flash(msg, cat)
            return runtime.redirect(runtime.url_for('users_admin'))
        if runtime.request.method == 'POST':
            a = runtime.request.form.get('action')
            f = runtime.request.form
            uid = int(f['user_id']) if (f.get('user_id') or '').isdigit() else 0
            role = f.get('role')
            tgt = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone() if uid else None
            if a in ('create', 'update') and len(f.getlist('can_infra')) > 1:
                c.close()
                return ('Invalid capability request', 400)
            if a == 'create' and (not sysadm) and (not me['org_unit_id']):
                c.close()
                runtime.abort(403)
            if a == 'create' and (not sysadm) and f.get('can_infra'):
                c.close()
                return ('Access Denied', 403)
            if a == 'create':
                un = f.get('username', '').strip()[:64]
                pw = f.get('password', '')
                if role not in runtime.ROLES or (role == 'System Administrator' and (not sysadm)):
                    return back('Role not permitted.')
                if not un or not f.get('full_name', '').strip():
                    return back('Full name and username are required.')
                if f.get('email', '').strip() and (not runtime.EMAIL_RE.match(f.get('email', '').strip())):
                    return back('Invalid email address.')
                if not runtime.pw_ok(pw, un):
                    return back('The password must contain at least 12 characters.')
                if c.execute('SELECT 1 FROM users WHERE username=?', (un,)).fetchone():
                    return back('This username already exists.')
                c.execute('INSERT INTO users(username,password_hash,full_name,email,role,structure,sector,must_change,phone,institution,duty,can_infra,org_unit_id) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?)', (un, runtime.generate_password_hash(pw), f['full_name'].strip()[:100], f.get('email', '').strip()[:120], role, f.get('structure', '')[:100], f.get('sector', '')[:100], f.get('phone', '')[:40], f.get('institution', '')[:150], f.get('duty', '')[:150], 1 if f.get('can_infra') else 0, me['org_unit_id'] if not sysadm else None))
                c.commit()
                runtime.audit('Create', 'User', c.execute('SELECT id FROM users WHERE username=?', (un,)).fetchone()['id'], new=f'{un} / {role}')
                return back('User created. A password change is required at first login.', 'success')
            if not tgt:
                return back('User not found.')
            if not runtime.directory_can_edit_target(me, tgt, runtime.ORG, c):
                c.close()
                runtime.audit('AccessDenied', 'User', uid)
                return ('Access Denied', 403)
            if tgt['role'] == 'System Administrator' and (not sysadm):
                runtime.audit('AccessDenied', 'User', uid)
                return back('Only a System Administrator can manage System Administrator accounts.')
            protected_capability = bool(tgt['can_infra']) and (not bool(me['can_infra']))
            if not sysadm and protected_capability and (a in ('reset', 'activate', 'deactivate', 'delete') or (a == 'update' and role != tgt['role'])):
                c.close()
                runtime.abort(403)
            me_self = tgt['id'] == me['id']
            if a == 'update':
                infra_value = 1 if f.get('can_infra') else 0
                if not sysadm:
                    if 'can_infra' in f and infra_value != int(bool(tgt['can_infra'])):
                        c.close()
                        return ('Access Denied', 403)
                    infra_value = int(bool(tgt['can_infra']))
                if role not in runtime.ROLES or (role == 'System Administrator' and (not sysadm) and (tgt['role'] != role)):
                    return back('Role not permitted.')
                if me_self:
                    role = tgt['role']
                if f.get('email', '').strip() and (not runtime.EMAIL_RE.match(f.get('email', '').strip())):
                    return back('Invalid email address.')
                c.execute('UPDATE users SET full_name=?,email=?,role=?,structure=?,sector=?,phone=?,institution=?,duty=?,can_infra=?,auth_version=auth_version+? WHERE id=?', (f.get('full_name', '').strip()[:100] or tgt['full_name'], f.get('email', '').strip()[:120], role, f.get('structure', '')[:100], f.get('sector', '')[:100], f.get('phone', '')[:40], f.get('institution', '')[:150], f.get('duty', '')[:150], infra_value, int(role != tgt['role']), uid))
                c.commit()
                runtime.audit('Update', 'User', uid, tgt['role'], role)
                if infra_value != int(bool(tgt['can_infra'])):
                    runtime.audit('InfrastructureCapability', 'User', uid, str(int(bool(tgt['can_infra']))), str(infra_value))
                return back('Details saved.', 'success')
            if a == 'reset':
                pw = f.get('password', '').strip()
                gen = not pw
                if gen:
                    pw = runtime.secrets.token_urlsafe(12)
                elif not runtime.pw_ok(pw, tgt['username']):
                    return back('The password must contain at least 12 characters.')
                c.execute('UPDATE users SET password_hash=?,must_change=1,failed=0,locked_until=NULL,auth_version=auth_version+1 WHERE id=?', (runtime.generate_password_hash(pw), uid))
                c.commit()
                runtime.audit('PasswordReset', 'User', uid)
                return back(f"Temporary password for {tgt['username']}: {pw} (shown only now; the user must change it at the next login)." if gen else 'Password reset; the user must change it at the next login.', 'success')
            if a == 'activate':
                c.execute('UPDATE users SET active=1,failed=0,locked_until=NULL WHERE id=?', (uid,))
                c.commit()
                runtime.audit('Activate', 'User', uid)
                return back('Account reactivated.', 'success')
            if a in ('deactivate', 'delete'):
                if me_self:
                    return back('You cannot delete or deactivate your own account.')
                refs = c.execute('SELECT (SELECT count(*) FROM tickets WHERE requester_id=?1 OR assignee_id=?1 OR created_by=?1)+(SELECT count(*) FROM task_assignees WHERE user_id=?1)+(SELECT count(*) FROM timeline WHERE actor_id=?1)+(SELECT count(*) FROM audit WHERE actor_id=?1)+(SELECT count(*) FROM assets WHERE owner_id=?1)+(SELECT count(*) FROM services WHERE owner_id=?1)+(SELECT count(*) FROM teams WHERE owner_id=?1)+(SELECT count(*) FROM team_members WHERE user_id=?1)+(SELECT count(*) FROM boards WHERE owner_id=?1)+(SELECT count(*) FROM cards WHERE assignee_id=?1 OR creator_id=?1)+(SELECT count(*) FROM chat_messages WHERE from_id=?1 OR to_id=?1)+(SELECT count(*) FROM ticket_steps WHERE user_id=?1)+(SELECT count(*) FROM tasks WHERE created_by=?1) n', (uid,)).fetchone()['n']
                if a == 'delete' and (not refs):
                    c.execute('DELETE FROM users WHERE id=?', (uid,))
                    c.execute('DELETE FROM notifications WHERE user_id=?', (uid,))
                    c.commit()
                    runtime.audit('Delete', 'User', uid, tgt['username'])
                    return back('User permanently deleted.', 'success')
                c.execute('UPDATE users SET active=0,auth_version=auth_version+1 WHERE id=?', (uid,))
                c.commit()
                runtime.audit('Deactivate', 'User', uid, tgt['username'])
                return back('Account deactivated (sign-in disabled). Ticket and audit history is retained, so the account is not physically deleted.' if a == 'delete' else 'Account deactivated.', 'success')
            return back('Invalid action.')
        scope, args = runtime.directory_scope_sql(me, runtime.ORG, c)
        rows = c.execute('SELECT u.* FROM users u WHERE ' + scope + ' ORDER BY active DESC,full_name', args).fetchall()
        c.close()
        return runtime.render_template('users.html', now_str=runtime.now(), users=rows, roles=[r for r in runtime.ROLES if sysadm or r != 'System Administrator'], sysadm=sysadm, me=me)
    runtime.users_admin = users_admin

    @runtime.login_required
    def admin():
        if runtime.session.get('role') != 'System Administrator':
            return ('Access denied', 403)
        c = runtime.db()
        if runtime.request.method == 'POST':
            f = runtime.request.form['form']
            if f == 'user':
                if len(runtime.request.form['password']) < 12 or runtime.request.form['role'] not in runtime.ROLES:
                    runtime.flash('A password of at least 12 characters and a valid role are required.', 'danger')
                    c.close()
                    return runtime.redirect(runtime.url_for('admin'))
                c.execute('INSERT INTO users(username,password_hash,full_name,email,role,structure,sector,must_change,can_infra) VALUES(?,?,?,?,?,?,?,1,?)', (runtime.request.form['username'], runtime.generate_password_hash(runtime.request.form['password']), runtime.request.form['full_name'], runtime.request.form['email'], runtime.request.form['role'], runtime.request.form['structure'], runtime.request.form['sector'], 1 if runtime.request.form.get('can_infra') else 0))
                c.commit()
                runtime.audit('Create', 'User', 0, new=runtime.request.form['username'] + ' / ' + runtime.request.form['role'])
            elif f == 'group':
                c.execute('INSERT OR IGNORE INTO support_groups(name,description) VALUES(?,?)', (runtime.request.form['name'], runtime.request.form.get('description', '')))
            elif f == 'smtp':
                for k in runtime.SMTP_KEYS:
                    v = runtime.request.form.get(k, '')
                    if k == 'smtp_password':
                        v = runtime.enc_secret(v) if v else runtime.setting(k)
                    elif k == 'smtp_verify':
                        v = '1' if runtime.request.form.get(k) else '0'
                    elif k == 'base_url':
                        v = v.strip().rstrip('/')[:200]
                        if v and '@' in v:
                            runtime.flash('The base URL must be a web address (e.g. https://host), not an email address. Changes were not saved.', 'danger')
                            continue
                        if v and (not v.lower().startswith(('http://', 'https://'))):
                            v = 'https://' + v
                    c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, v))
                c.commit()
                runtime.audit('Update', 'Settings', 0, new='SMTP/Email')
            elif f == 'announcement':
                cur = c.execute('INSERT INTO announcements(title,message,kind,created_by,created_at) VALUES(?,?,?,?,?)', (runtime.request.form['title'], runtime.request.form['message'], runtime.request.form['kind'], runtime.session['uid'], runtime.now()))
                users = c.execute('SELECT id,email,full_name FROM users WHERE active=1').fetchall()
                items = []
                nomail = 0
                for u in users:
                    c.execute('INSERT INTO notifications(user_id,title,message,kind,created_at) VALUES(?,?,?,?,?)', (u['id'], runtime.request.form['title'], runtime.request.form['message'], runtime.request.form['kind'], runtime.now()))
                    if runtime.request.form.get('email_all'):
                        if u['email']:
                            items.append((u['email'], f"OpenITSM – {runtime.request.form['title']}", runtime.request.form['message']))
                        else:
                            nomail += 1
                c.commit()
                runtime.send_bulk(items)
                runtime.audit('Create', 'Announcement', cur.lastrowid, new=runtime.request.form['title'][:100])
                runtime.flash(f'Announcement delivered to {len(users)} active users in the system' + (f'; email to {len(items)}' + (f' ({nomail} without a registered email address)' if nomail else '') if runtime.request.form.get('email_all') else '') + '.', 'success')
            c.commit()
            c.close()
            return runtime.redirect(runtime.url_for('admin'))
        users = c.execute('SELECT * FROM users ORDER BY full_name').fetchall()
        groups = c.execute('SELECT * FROM support_groups ORDER BY name').fetchall()
        sec_counts = {r[0]: r[1] for r in c.execute("SELECT sector,count(*) FROM users WHERE sector<>'' AND active=1 GROUP BY sector")}
        c.close()
        smtp = {k: runtime.setting(k) for k in runtime.SMTP_KEYS}
        smtp['smtp_password'] = ''
        smtp['has_password'] = bool(runtime.setting('smtp_password'))
        c = runtime.db()
        mail_log = c.execute('SELECT * FROM email_log ORDER BY id DESC LIMIT 15').fetchall()
        c.close()
        return runtime.render_template('admin.html', sec_counts=sec_counts, users=users, groups=groups, smtp=smtp, mail_log=mail_log, default_sender=runtime.DEFAULT_SENDER, detected_url=runtime.request.host_url.rstrip('/'))
    runtime.admin = admin

    @runtime.login_required
    def test_email():
        if runtime.session.get('role') != 'System Administrator':
            return ('Access denied', 403)
        ok, msg = runtime.send_email(runtime.request.form['to'], '[OpenITSM] Email delivery test', 'This is a test email from OpenITSM. If you can read this, SMTP is working.\n\nSystem URL: ' + (runtime.base_url() or '-'))
        runtime.flash(msg, 'success' if ok else 'danger')
        return runtime.redirect(runtime.url_for('admin'))
    runtime.test_email = test_email

    @runtime.login_required
    def directory():
        me = runtime.current()
        can_edit = me['role'] in runtime.DIR_EDIT
        c = runtime.db()
        if runtime.request.method == 'POST':
            if not can_edit:
                c.close()
                runtime.audit('AccessDenied', 'Directory', 0)
                return ('Access Denied', 403)
            f = runtime.request.form
            uid = int(f['user_id']) if (f.get('user_id') or '').isdigit() else 0
            tgt = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
            email = f.get('email', '').strip()[:120]
            phone = f.get('phone', '').strip()[:40]
            name = f.get('full_name', '').strip()[:100]
            err = None
            if not tgt:
                err = 'User not found.'
            elif not runtime.directory_can_edit_target(me, tgt, runtime.ORG, c):
                err = 'Access denied for this organizational scope.'
            elif not name:
                err = 'Full name is required.'
            elif email and (not runtime.EMAIL_RE.match(email)):
                err = 'Invalid email address.'
            elif phone and (not runtime.PHONE_RE.match(phone)):
                err = 'Invalid phone number.'
            if err:
                c.close()
                runtime.flash(err, 'danger')
                return runtime.redirect(runtime.url_for('directory'))
            c.execute('UPDATE users SET full_name=?,email=?,phone=?,institution=?,structure=?,sector=?,duty=? WHERE id=?', (name, email, phone, f.get('institution', '').strip()[:150], f.get('structure', '').strip()[:100], f.get('sector', '').strip()[:100], f.get('duty', '').strip()[:150], uid))
            c.commit()
            c.close()
            runtime.audit('DirectoryEdit', 'User', uid, new=name)
            runtime.flash('Details for ' + name + ' were saved.', 'success')
            return runtime.redirect(runtime.url_for('directory'))
        scope, params = runtime.directory_scope_sql(me, runtime.ORG, c)
        rows = c.execute('SELECT u.id,u.full_name,u.email,u.phone,u.institution,u.role,u.structure,u.sector,u.duty FROM users u WHERE u.active=1 AND ' + scope + ' ORDER BY u.full_name', params).fetchall()
        c.close()
        return runtime.render_template('directory.html', users=rows, can_edit=can_edit, me=me)
    runtime.directory = directory

    @runtime.login_required
    def profile():
        u = runtime.current()
        if runtime.request.method == 'POST':
            f = runtime.request.form
            if f.get('action') == 'skip':
                runtime.flash('You can complete your details later in “My profile”.', 'success')
                return runtime.redirect(runtime.url_for('dashboard'))
            name = f.get('full_name', '').strip()[:100]
            email = f.get('email', '').strip()[:120]
            phone = f.get('phone', '').strip()[:40]
            inst = f.get('institution', '').strip()[:150]
            duty = f.get('duty', '').strip()[:150]
            sector = f.get('sector', '').strip()[:100]
            err = None
            if not name:
                err = 'Full name is required.'
            elif email and (not runtime.EMAIL_RE.match(email)):
                err = 'Invalid email address.'
            elif phone and (not runtime.PHONE_RE.match(phone)):
                err = 'Invalid phone number.'
            if err:
                runtime.flash(err, 'danger')
            else:
                done = 1 if email and phone and inst and duty else 0
                c = runtime.db()
                c.execute('UPDATE users SET full_name=?,email=?,phone=?,institution=?,duty=?,sector=?,profile_done=? WHERE id=?', (name, email, phone, inst, duty, sector, done, u['id']))
                c.commit()
                c.close()
                runtime.session['name'] = name
                runtime.audit('ProfileUpdate', 'User', u['id'])
                if done:
                    runtime.flash('Details saved. Your email address will be used for ticket notifications.', 'success')
                    return runtime.redirect(runtime.url_for('dashboard'))
                runtime.flash('Details saved, but your profile is incomplete (email, phone, institution and position are required).', 'danger')
                return runtime.redirect(runtime.url_for('profile'))
            runtime.g.pop('cu', None)
            u = runtime.current()
        return runtime.render_template('profile.html', u=u)
    runtime.profile = profile
