"""Targeted B01-B08 regression cases, run by the isolated HTTP fixture."""
import csv
import json
import io
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


class BlockerCases:
    def test_b01_ticket_transition_matrix_all_roles_and_visibility_modes(self):
        for mode in ('org','legacy'):
            for uid in range(1,10):
                self.setUp()
                self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
                self.execute('UPDATE tickets SET assignee_id=4 WHERE id=101')
                self.execute("UPDATE tasks SET status='Completed' WHERE ticket_id=101")
                self.actor(uid)
                with self.subTest(mode=mode,uid=uid):
                    if uid in (7,8,9):
                        self.assertEqual(self.post('/tickets/101',action='status',status='In Progress').status_code,403)
                        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[('Open',)])
                        continue
                    for state in ('Assigned','In Progress','Waiting','In Progress','Resolved','In Progress','Resolved','Closed'):
                        self.assertEqual(self.post('/tickets/101',action='status',status=state,resolution_note='Synthetic transition evidence').status_code,302)
                        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[(state,)])
                    self.post('/tickets/101',action='status',status='Assigned',resolution_note='FORGED closed reopen')
                    self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[('Closed',)])
    def test_b07_commit_failure_rolls_back_privileges_and_releases_locks(self):
        self.actor(1); before=self.rows('SELECT * FROM users WHERE id=4')
        with patch.object(self.m,'commit_request_connection',side_effect=sqlite3.OperationalError('Synthetic commit failure')):
            self.assertEqual(self.post('/users',action='update',user_id='4',role='Operational Operator',can_infra='1').status_code,503)
        self.assertEqual(self.rows('SELECT * FROM users WHERE id=4'),before)
        self.assertEqual(self.rows('SELECT id FROM audit WHERE object_id=4'),[])
        self.actor(1)
        self.assertEqual(self.post('/admin',form='group',name='Synthetic after failed commit').status_code,302)

    def test_b07_notifications_wait_for_atomic_ticket_commit(self):
        import threading
        self.execute("UPDATE users SET email='synthetic@example.invalid' WHERE id=4")
        self.actor(1); completed=threading.Event(); observed=[]
        def delivered(*args,**kwargs):
            observed.append(bool(self.rows("SELECT id FROM tickets WHERE title='Synthetic atomic success'")))
            completed.set()
            return True,'Synthetic delivery'
        payload=dict(type='Service Request',priority='Medium',description='Synthetic',unit_id='2',assignee_id='4')
        with patch.object(self.m,'send_async',side_effect=self.real_send_async),patch.object(self.m,'send_email',side_effect=delivered):
            with patch.object(self.m,'commit_request_connection',side_effect=sqlite3.OperationalError('Synthetic commit failure')):
                self.assertEqual(self.post('/tickets/new',title='Synthetic atomic failure',**payload).status_code,503)
            self.assertFalse(completed.wait(0.1))
            self.assertEqual(self.rows("SELECT id FROM tickets WHERE title='Synthetic atomic failure'"),[])
            self.assertEqual(self.rows('SELECT id FROM ticket_steps'),[])
            self.assertEqual(self.rows('SELECT id FROM notifications WHERE user_id=4'),[])
            self.actor(1)
            self.assertEqual(self.post('/tickets/new',title='Synthetic atomic success',**payload).status_code,302)
            self.assertTrue(completed.wait(5))
        self.assertEqual(observed,[True])
    def test_b07_audit_failure_rolls_back_privilege_change(self):
        self.actor(1); before=self.rows('SELECT * FROM users WHERE id=4')
        with patch.object(self.m,'audit',side_effect=sqlite3.OperationalError('Synthetic audit failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.post('/users',action='update',user_id='4',role='Operational Operator',can_infra='1')
        self.assertEqual(self.rows('SELECT * FROM users WHERE id=4'),before)
    def test_b02_unit_head_grants_cannot_expand_admin_authority(self):
        self.actor(5)
        fields={'unit_'+str(uid):'2' for uid in (2,3,4,5,6,7,9)}
        self.assertEqual(self.post('/org',action='assign_users',head_5='1',**fields).status_code,403)
        self.assertEqual(self.rows('SELECT org_head FROM users WHERE id=5'),[(0,)])
        self.execute('UPDATE users SET org_head=1 WHERE id=4')
        self.assertEqual(self.post('/users',action='reset',user_id='4',password='FORGED RESET!12345').status_code,403)
        self.execute('UPDATE users SET org_unit_id=3 WHERE id=5')
        self.assertEqual(self.post('/org',action='assign_users',unit_5='3',head_5='1').status_code,403)
        self.assertEqual(self.rows('SELECT org_head FROM users WHERE id=5'),[(0,)])

    def test_b02_password_reset_cannot_inherit_privileged_capability_or_queue(self):
        self.execute('UPDATE users SET can_infra=1 WHERE id=4')
        self.actor(5); before=self.rows('SELECT * FROM users WHERE id=4')
        self.assertEqual(self.post('/users',action='reset',user_id='4',password='FORGED RESET!12345').status_code,403)
        self.assertEqual(self.rows('SELECT * FROM users WHERE id=4'),before)
        self.execute('UPDATE users SET can_infra=0 WHERE id=4')
        self.execute('INSERT INTO task_assignees VALUES(102,4)')
        self.assertEqual(self.post('/users',action='reset',user_id='4',password='FORGED RESET!12345').status_code,403)
        self.assertEqual(self.post('/users',action='update',user_id='4',role='Requester').status_code,403)
    def test_b04_locked_and_unknown_accounts_have_generic_responses(self):
        self.execute("UPDATE users SET locked_until='2099-01-01 00:00:00' WHERE id=1")
        messages=[]
        for name in ('admin','missing-synthetic'):
            client=self.m.app.test_client(); client.get('/login')
            with client.session_transaction() as s: token=s['csrf']
            response=client.post('/login',data={'csrf_token':token,'username':name,'password':'SyntheticOnly!12345'})
            self.assertEqual(response.status_code,200)
            with client.session_transaction() as s:
                self.assertNotIn('uid',s)
            messages.append(response.data.replace(token.encode(),b'CSRF'))
        self.assertEqual(messages[0],messages[1])
        self.assertEqual(self.rows('SELECT count(*) FROM login_attempts'),[(2,)])

    def test_b05_actual_backup_iteration_retention_and_restore(self):
        import os
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix='openitsm-backup-') as tmp:
            old=Path(tmp)/'synthetic-old.db'; old.write_bytes(b'Synthetic retention fixture')
            timestamp=time.time()-40*86400; os.utime(old,(timestamp,timestamp))
            with patch.object(self.m,'BACKUPS',tmp),patch.object(self.m.time,'sleep',side_effect=StopIteration):
                with self.assertRaises(StopIteration): self.m.backup_worker()
            self.assertFalse(old.exists())
            files=list(Path(tmp).glob('itsm-*.db')); self.assertEqual(len(files),1)
            source=sqlite3.connect(files[0]); restored=sqlite3.connect(Path(tmp)/'restored.sqlite')
            try:
                source.backup(restored)
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(restored.execute('SELECT code FROM tickets ORDER BY id').fetchall(),[('SYN-101',),('SYN-102',)])
            finally: source.close(); restored.close()
    def test_b02_stale_foreign_membership_cannot_leak_summary_or_personal_cards(self):
        self.execute("INSERT INTO team_members(team_id,user_id,role) VALUES(901,8,'Member')")
        self.execute('UPDATE boards SET team_id=901 WHERE id=901')
        self.execute('UPDATE cards SET assignee_id=8 WHERE id=901')
        self.actor(8)
        for path in ('/space','/'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn(b'PRIVATE_CARD',response.data)
            self.assertNotIn(b'PRIVATE_TEAM',response.data)
        self.assertEqual(self.client.get('/space/board/901').status_code,403)

    def test_b02_private_parent_and_aggregate_scope_cannot_be_bypassed(self):
        from flask import template_rendered
        self.execute("UPDATE services SET name='FOREIGN PARENT',unit_id=6 WHERE id=2")
        self.execute("INSERT INTO services(id,name,parent_service_id,is_main,unit_id) VALUES(200,'LEGACY CHILD',2,0,NULL)")
        self.execute("INSERT INTO services(id,name,parent_service_id,is_main,unit_id) VALUES(201,'FOREIGN CHILD',1,0,6)")
        self.actor(8); contexts=[]
        def capture(sender,template,context,**extra): contexts.append(context)
        with template_rendered.connected_to(capture,self.m.app): response=self.client.get('/services')
        self.assertNotIn(b'LEGACY CHILD',response.data)
        self.actor(5); self.assertNotIn(b'LEGACY CHILD',self.client.get('/assets').data)
        self.actor(8)
        self.assertNotIn(b'FOREIGN PARENT',response.data)
        self.assertEqual(next(r['subsection_count'] for r in contexts[-1]['services'] if r['id']==1),0)
        self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='FORGED',description='Synthetic',service_id='200').status_code,403)
    def test_b04_signing_key_rotation_invalidates_old_cookie(self):
        self.actor(1)
        with patch.dict(self.m.app.config,SECRET_KEY='synthetic-rotated-key-'*3):
            self.assertIn('/login',self.client.get('/users').location)

    def test_b06_formula_prefixes_remain_literal(self):
        self.actor(8)
        for text in ('=1+1','+1+1','-1+1','@SUM(1)','\t=1','\r=1','\n=1','  =1'):
            self.execute('UPDATE tickets SET title=? WHERE id=101',(text,))
            response=self.client.get('/reports/export/tickets/csv')
            rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')),delimiter=';'))
            self.assertEqual(rows[1][2],"'"+text)

    def test_b06_audit_pagination_and_export_have_identical_scope(self):
        from flask import template_rendered
        self.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<101) INSERT INTO audit(actor_id,action,object_type,object_id,new_value,created_at) SELECT 1,'SyntheticPage','Ticket',101,'Synthetic row '||x,'2026-11-05 10:00:00' FROM n")
        self.execute("INSERT INTO audit(actor_id,action,object_type,object_id,new_value,created_at) VALUES(1,'SyntheticPage','Ticket',102,'FOREIGN PAGE','2026-11-05 10:00:00')")
        self.actor(5)
        for page,count in ((1,100),(2,1)):
            contexts=[]
            def capture(sender,template,context,**extra): contexts.append(context)
            with template_rendered.connected_to(capture,self.m.app):
                response=self.client.get('/audit?action=SyntheticPage&page='+str(page))
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(contexts[-1]['rows']),count)
            self.assertEqual(contexts[-1]['total'],101)
            self.assertEqual(contexts[-1]['pages'],2)
            self.assertNotIn(b'FOREIGN PAGE',response.data)
        response=self.client.get('/audit/export/csv?action=SyntheticPage')
        rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),102)
        self.assertNotIn(b'FOREIGN PAGE',response.data)
        self.assertEqual(self.client.get('/audit?date_from=invalid').status_code,400)
        self.assertEqual(self.client.get('/audit?actor=invalid').status_code,400)
    def test_b01_pending_workflow_cannot_be_bypassed_and_closed_tasks_are_immutable(self):
        self.actor(1)
        self.post('/tickets/101',action='step_add',step_user='4')
        self.post('/tickets/101',action='step_add',step_user='2')
        self.execute("UPDATE tasks SET status='Completed' WHERE id=101")
        self.post('/tickets/101',action='status',status='Resolved',resolution_note='Attempted workflow bypass')
        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[('Open',)])
        self.actor(4)
        self.post('/tickets/101',action='step_done',note='')
        self.assertEqual(self.rows('SELECT status FROM ticket_steps WHERE ticket_id=101 ORDER BY seq'),[('Active',),('Pending',)])
        self.post('/tickets/101',action='step_done',note='Synthetic first signature')
        self.actor(2); self.post('/tickets/101',action='step_done',note='Synthetic final signature')
        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[('Resolved',)])
        self.assertEqual(self.post('/tickets/101',action='step_done',note='FORGED replay').status_code,403)
        self.actor(1); self.post('/tickets/101',action='status',status='Closed',resolution_note='Synthetic close')
        for action in ('start','update','reopen','subtask'):
            self.assertEqual(self.post('/tasks/101/do',action=action,note='FORGED closed mutation',task_title='FORGED',task_assignees='4').status_code,403)
        self.assertEqual(self.rows('SELECT status FROM tasks WHERE id=101'),[('Completed',)])
    def test_b02_auditor_capability_cannot_override_read_only_policy(self):
        self.execute('UPDATE users SET can_infra=1 WHERE id=9')
        self.execute('UPDATE services SET unit_id=2 WHERE id=1')
        self.actor(9)
        self.assertEqual(self.post('/assets',name='FORGED AUDIT WRITE').status_code,403)
        self.assertEqual(self.post('/services',action='rename_service',service_id='1',name='FORGED AUDIT WRITE').status_code,403)
        self.execute('UPDATE tickets SET assignee_id=7 WHERE id=101')
        self.execute('INSERT INTO task_assignees VALUES(101,7)')
        self.actor(7)
        self.assertEqual(self.post('/tickets/101',action='status',status='In Progress').status_code,403)
        self.assertEqual(self.post('/tasks/101/complete',completion_notes='FORGED LEGACY WRITE').status_code,403)

    def test_b02_team_invitation_cannot_create_foreign_membership(self):
        self.actor(8); self.post('/space',action='team_create',name='Synthetic bounded team')
        tid=self.rows("SELECT id FROM teams WHERE name='Synthetic bounded team'")[0][0]
        self.assertEqual(self.post('/space/team/'+str(tid),action='add_member',user_id='99').status_code,403)
        self.assertEqual(self.rows('SELECT * FROM team_members WHERE team_id=? AND user_id=99',(tid,)),[])

    def test_b07_empty_legacy_password_hash_cannot_authenticate(self):
        self.client.get('/login')
        self.assertEqual(self.client.post('/login',data={'csrf_token':self.session_token(),'username':'synthetic4','password':'invalid'}).status_code,200)
        with self.client.session_transaction() as s: self.assertNotIn('uid',s)
    def test_b01_all_staff_actions_role_and_foreign_denial_matrix(self):
        actions=[dict(action='comment',comment='FORGED'),dict(action='status',status='In Progress'),dict(action='task',task_title='FORGED',task_assignees='4'),dict(action='step_add',step_user='4'),dict(action='step_done',note='FORGED SIGNATURE')]
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in range(2,10):
                self.actor(uid)
                for fields in actions:
                    before=self.rows('SELECT * FROM tickets ORDER BY id')
                    with self.subTest(mode=mode,uid=uid,action=fields['action']):
                        self.assertEqual(self.post('/tickets/102',**fields).status_code,403)
                        self.assertEqual(self.rows('SELECT * FROM tickets ORDER BY id'),before)
        self.actor(8)
        for fields in actions[1:]: self.assertEqual(self.post('/tickets/101',**fields).status_code,403)

    def test_b06_role_mode_export_row_filter_and_pagination_parity(self):
        from flask import template_rendered
        self.execute("UPDATE tickets SET status='Resolved',created_at='2020-01-01 00:00:00' WHERE id=102")
        self.execute("UPDATE tasks SET created_at='2020-01-01 00:00:00' WHERE id=102")
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in range(1,10):
                self.actor(uid)
                expected=['SYN-102','SYN-101'] if uid==1 else [] if uid in (4,9) else ['SYN-101']
                contexts=[]
                def capture(sender,template,context,**extra): contexts.append(context)
                with template_rendered.connected_to(capture,self.m.app): self.client.get('/tickets')
                self.assertEqual([r['code'] for r in contexts[-1]['tickets']],expected)
                for kind in ('tickets','tasks'):
                    response=self.client.get('/reports/export/'+kind+'/csv')
                    rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')),delimiter=';'))
                    self.assertEqual([r[0] for r in rows[1:]],expected)
                    import xml.etree.ElementTree as ET
                    xlsx=self.client.get('/reports/export/'+kind+'/xlsx')
                    with zipfile.ZipFile(io.BytesIO(xlsx.data)) as archive:
                        sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                        actual=[row.find('m:c/m:is/m:t',ns).text for row in sheet.findall('.//m:row',ns)[1:]]
                        self.assertEqual(actual,expected)
                        decoded=[]
                        for row in sheet.findall('.//m:row',ns):
                            # CSV adds a literal-prefix defence; XLSX already uses typed inline strings.
                            decoded.append([self.m._csv_safe(''.join(cell.itertext())) if cell.get('t')=='inlineStr' else cell.findtext('m:v','',ns) for cell in row.findall('m:c',ns)])
                        self.assertEqual(decoded,rows)

                    for query in ('status=Open','date_from=2026-01-01','date_to=2025-01-01','type=Task'):
                        response=self.client.get('/reports/export/'+kind+'/csv?'+query)
                        rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')),delimiter=';'))
                        wanted=[] if query=='type=Task' else ['SYN-102'] if query=='date_to=2025-01-01' and uid==1 else [] if query=='date_to=2025-01-01' else [x for x in expected if x=='SYN-101']
                        self.assertEqual([r[0] for r in rows[1:]],wanted)
        self.actor(8)
        summary=list(csv.reader(io.StringIO(self.client.get('/reports/export/summary/csv').data.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(summary[1][2],'1')
        for query in ('status=Unknown','type=Invalid','date_from=2026-02-31'):
            self.assertEqual(self.client.get('/reports/export/tickets/csv?'+query).status_code,400)

    def test_b06_populated_login_popup_scoped_in_both_modes(self):
        from flask import template_rendered
        self.execute('UPDATE tickets SET assignee_id=8 WHERE id=102')
        self.execute('INSERT INTO task_assignees VALUES(102,8)')
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            self.actor(8)
            with self.client.session_transaction() as s: s['popup']=1
            contexts=[]
            def capture(sender,template,context,**extra): contexts.append(context)
            with template_rendered.connected_to(capture,self.m.app): response=self.client.get('/')
            self.assertEqual(response.status_code,200)
            self.assertIsNone(contexts[-1]['login_popup'])
            self.assertNotIn(b'SECRET_102',response.data)

    def test_b07_csrf_unicode_oversize_and_payload_escaping(self):
        self.actor(1)
        self.assertEqual(self.client.post('/admin',data={'csrf_token':'ë','form':'group','name':'FORGED'}).status_code,403)
        with patch.dict(self.m.app.config,MAX_CONTENT_LENGTH=128):
            self.assertEqual(self.client.post('/profile',data={'csrf_token':'synthetic-csrf','full_name':'x'*1000}).status_code,413)
        self.actor(8)
        self.post('/tickets/101',action='comment',comment='<script>window.phase0attack=1</script>')
        body=self.client.get('/tickets/101').data
        self.assertNotIn(b'<script>window.phase0attack',body)
        self.assertIn(b'&lt;script&gt;',body)
        self.assertEqual(self.client.get('/api/users/search?q=%27%20OR%201%3D1--').get_json(),[])
        self.actor(1)
        response=self.client.post('/admin',data={'csrf_token':'synthetic-csrf','form':'user','username':'admin','password':'SyntheticOnly!12345','full_name':'duplicate','email':'synthetic@example.invalid','role':'Requester','structure':'A','sector':'A'},headers={'Referer':'http://localhost//evil.invalid/path'})
        self.assertFalse(response.location.startswith('//'))
    def test_b02_delegation_prevents_foreign_visibility_grants(self):
        self.execute("INSERT INTO users(id,username,full_name,role,org_unit_id,active) VALUES(100,'foreign-tech','FOREIGN TECH','Operational Operator',6,1)")
        self.actor(3)
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            before=self.rows('SELECT * FROM ticket_steps')
            self.assertEqual(self.post('/tickets/101',action='step_add',step_user='100').status_code,403)
            self.assertEqual(self.rows('SELECT * FROM ticket_steps'),before)
            self.assertEqual(self.post('/tickets/101',action='task',task_title='FORGED',task_assignees='100').status_code,403)
            self.assertEqual(self.rows("SELECT id FROM tasks WHERE title='FORGED'"),[])
            self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='FORGED',description='Synthetic',unit_id='6').status_code,403)
            self.assertEqual(self.post('/tickets/new',type='Service Request',priority='Medium',title='FORGED',description='Synthetic',unit_id='2',chain_users='100').status_code,403)
        self.actor(100)
        self.assertEqual(self.client.get('/tickets/101').status_code,403)
        self.actor(3)
        self.assertEqual(self.post('/tickets/101',action='step_add',step_user='4').status_code,302)
        self.actor(4); self.assertEqual(self.client.get('/tickets/101').status_code,200)

    def test_b02_scoped_metadata_and_central_tickets_in_both_modes(self):
        self.execute("UPDATE services SET unit_id=6,name='FOREIGN_SERVICE' WHERE id=2")
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in (2,3,4,5,6,7,8,9):
                self.actor(uid)
                for path,marker in (('/services',b'FOREIGN_SERVICE'),('/directory',b'FOREIGN_USER'),('/api/users/search?q=FOREIGN',b'FOREIGN_USER')):
                    self.assertNotIn(marker,self.client.get(path).data)
            self.actor(5)
            self.assertNotIn(b'FOREIGN_USER',self.client.get('/users').data)
            self.assertEqual(self.client.get('/tickets/102').status_code,403)
            self.assertNotIn(b'FOREIGN_USER',self.client.get('/org').data)

    def test_b02_root_second_organization_and_same_name_scope(self):
        self.execute("INSERT INTO org_units(id,name,kind) VALUES(90,'Second synthetic organization','ORG')")
        self.execute("INSERT INTO org_units(id,parent_id,name,kind) VALUES(91,90,'IT Operations','UNIT')")
        self.execute('UPDATE users SET org_head=1 WHERE id=5')
        self.execute('UPDATE tickets SET unit_id=91,structure=? WHERE id=102',('Unit A',))
        self.execute('UPDATE users SET org_unit_id=91 WHERE id=99')
        self.actor(5)
        self.assertEqual(self.client.get('/tickets/102').status_code,403)
        self.execute('UPDATE users SET org_unit_id=1 WHERE id=5')
        self.assertEqual(self.client.get('/tickets/102').status_code,403)
        self.assertNotIn(b'FOREIGN_USER',self.client.get('/directory').data)
        self.actor(1); self.assertEqual(self.client.get('/tickets/102').status_code,200)

    def test_b03_get_head_options_do_not_acknowledge_read_state(self):
        self.execute("INSERT INTO notifications(user_id,title) VALUES(8,'Synthetic unread')")
        self.execute("INSERT INTO notifications(user_id,title) VALUES(99,'Foreign unread')")
        self.execute("INSERT INTO chat_messages(from_id,to_id,body) VALUES(2,8,'Synthetic unread chat')")
        self.actor(8)
        before=(self.rows('SELECT * FROM notifications'),self.rows('SELECT * FROM chat_messages'))
        for method in ('GET','HEAD','OPTIONS'):
            for path in ('/notifications','/api/chat/thread?with=2'):
                self.assertEqual(self.client.open(path,method=method).status_code,200)
        self.assertEqual((self.rows('SELECT * FROM notifications'),self.rows('SELECT * FROM chat_messages')),before)
        self.assertEqual(self.client.post('/notifications/read').status_code,403)
        self.assertEqual(self.client.post('/api/chat/read',json={'with':2}).status_code,403)
        self.assertEqual(self.post('/notifications/read').status_code,302)
        self.assertEqual(self.rows('SELECT user_id,is_read FROM notifications ORDER BY user_id'),[(8,1),(99,0)])
        self.assertEqual(self.client.post('/api/chat/read',json={'with':2},headers={'X-CSRF':'synthetic-csrf'}).status_code,200)
        self.assertIsNotNone(self.rows('SELECT read_at FROM chat_messages WHERE to_id=8')[0][0])
        self.assertEqual(self.rows('SELECT read_at FROM chat_messages WHERE to_id=1'),[(None,)])

    def test_b04_epochless_and_absolute_expired_sessions_rejected(self):
        self.actor(1)
        with self.client.session_transaction() as s: s.pop('auth_version')
        self.assertIn('/login',self.client.get('/users').location)
        self.actor(1)
        with self.client.session_transaction() as s: s['issued_at']=time.time()-8*3600-1
        self.assertIn('/login',self.client.get('/users').location)
        self.actor(1)
        with self.client.session_transaction() as s: s['issued_at']=time.time()+3600
        self.assertIn('/login',self.client.get('/users').location)

    def test_b04_password_epoch_compare_and_swap(self):
        self.actor(1); before=self.rows('SELECT password_hash FROM users WHERE id=1')
        real=self.m.generate_password_hash
        def competing_change(value):
            c=sqlite3.connect(self.m.DB)
            try: c.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=1'); c.commit()
            finally: c.close()
            return real(value)
        with patch.object(self.m,'generate_password_hash',side_effect=competing_change):
            self.assertEqual(self.post('/account',current='SyntheticOnly!12345',new='SyntheticNew!12345',confirm='SyntheticNew!12345').status_code,409)
        self.assertEqual(self.rows('SELECT password_hash FROM users WHERE id=1'),before)

    def test_b04_persistent_concurrent_ip_throttle(self):
        def attempt(_):
            client=self.m.app.test_client()
            with client.session_transaction() as s: s['csrf']='parallel-token'
            return client.post('/login',data={'csrf_token':'parallel-token','username':'missing-synthetic','password':'invalid'}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool: codes=list(pool.map(attempt,range(24)))
        self.assertEqual(codes.count(429),4)
        self.assertEqual(self.rows('SELECT count(*) FROM login_attempts'),[(20,)])
        self.m.FAILS.clear()  # Simulate loss of the former process-local throttle.
        self.assertEqual(attempt(25),429)

    def test_b01_main_ticket_status_and_direct_task_actions(self):
        self.actor(1)
        self.assertEqual(self.post('/tickets/101',action='task',task_title='Synthetic direct task',task_assignees='4').status_code,302)
        self.assertEqual(self.rows("SELECT ticket_id FROM tasks WHERE title='Synthetic direct task'"),[(101,)])
        self.post('/tickets/101',action='status',status='Resolved',resolution_note='Synthetic completion')
        self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[('Open',)])
        self.execute("UPDATE tasks SET status='Completed' WHERE ticket_id=101")
        for state in ('In Progress','Resolved','Closed'):
            self.assertEqual(self.post('/tickets/101',action='status',status=state,resolution_note='Synthetic completion').status_code,302)
            self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[(state,)])
        self.assertEqual(self.post('/tickets/101',action='task',task_title='FORGED CLOSED',task_assignees='4').status_code,403)

    def test_b01_admin_user_form_and_org_settings_backfill(self):
        self.actor(1)
        self.assertEqual(self.post('/admin',form='user',username='synthetic-admin-form',password='SyntheticOnly!12345',full_name='Synthetic account',email='synthetic@example.invalid',role='Requester',structure='A',sector='A').status_code,302)
        self.assertEqual(self.rows("SELECT role,must_change FROM users WHERE username='synthetic-admin-form'"),[('Requester',1)])
        self.execute('UPDATE services SET unit_id=2 WHERE id=1')
        self.execute('UPDATE tickets SET unit_id=NULL,service_id=1 WHERE id=101')
        self.post('/org',action='settings',mode='legacy',intake_unit_id='3')
        self.post('/org',action='settings',mode='org',intake_unit_id='3',confirm='1')
        self.assertEqual(self.rows('SELECT unit_id FROM tickets WHERE id=101'),[(2,)])
        self.post('/org',action='unit_add',parent_id='2',name='Synthetic movable unit')
        uid=self.rows("SELECT id FROM org_units WHERE name='Synthetic movable unit'")[0][0]
        self.assertEqual(self.post('/org',action='unit_move',id=str(uid),parent_id='3').status_code,302)
        self.assertEqual(self.rows('SELECT parent_id FROM org_units WHERE id=?',(uid,)),[(3,)])

    def test_b01_personal_team_task_creation_and_board_deletion(self):
        self.actor(8)
        self.assertEqual(self.post('/profile',action='skip').status_code,302)
        self.assertEqual(self.post('/space',action='task_add',title='Synthetic personal task').status_code,302)
        bid=self.rows("SELECT board_id FROM cards WHERE title='Synthetic personal task'")[0][0]
        self.assertEqual(self.post('/space/board/'+str(bid),action='board_delete',confirm='1').status_code,302)
        self.assertEqual(self.rows('SELECT id FROM cards WHERE board_id=?',(bid,)),[])
        self.assertEqual(self.rows('SELECT id FROM board_lists WHERE board_id=?',(bid,)),[])
        self.post('/space',action='team_create',name='Synthetic task team')
        tid=self.rows("SELECT id FROM teams WHERE name='Synthetic task team'")[0][0]
        self.post('/space/team/'+str(tid),action='add_member',user_id='4')
        self.assertEqual(self.post('/space',action='task_add',title='Synthetic team task',dest='t:'+str(tid)+':4').status_code,302)
        self.assertEqual(self.rows("SELECT assignee_id FROM cards WHERE title='Synthetic team task'"),[(4,)])

    def test_b06_exact_csv_xlsx_ticket_ids_and_formula_safety(self):
        import xml.etree.ElementTree as ET
        self.execute("UPDATE tickets SET title='=SYNTHETIC_FORMULA' WHERE id=101")
        self.actor(8)
        response=self.client.get('/reports/export/tickets/csv')
        rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),2)
        self.assertIn('SYN-101',rows[1]); self.assertNotIn('SYN-102',response.data.decode())
        self.assertIn("'=SYNTHETIC_FORMULA",rows[1])
        response=self.client.get('/reports/export/tickets/xlsx')
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(len(sheet.findall('.//m:row',ns)),2)
            self.assertEqual(sheet.findall('.//m:f',ns),[])
            self.assertNotIn(b'SYN-102',archive.read('xl/worksheets/sheet1.xml'))

    def test_b06_scoped_audit_filters_counts_and_append_only(self):
        self.execute("INSERT INTO audit(actor_id,action,object_type,object_id,new_value,created_at) VALUES(1,'Synthetic','Ticket',101,'OWN AUDIT','2026-11-05 10:00:00')")
        self.execute("INSERT INTO audit(actor_id,action,object_type,object_id,new_value,created_at) VALUES(1,'Synthetic','Ticket',102,'FOREIGN AUDIT','2026-11-05 10:00:00')")
        for uid in (5,7,9):
            self.actor(uid)
            for path in ('/audit?action=Synthetic','/audit/export/csv?action=Synthetic'):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn(b'OWN AUDIT',response.data); self.assertNotIn(b'FOREIGN AUDIT',response.data)
        c=self.m.db()
        try:
            with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE audit SET new_value='FORGED'")
            c.rollback()
            with self.assertRaises(sqlite3.IntegrityError): c.execute('DELETE FROM audit')
            c.rollback()
        finally: c.close()

    def test_b07_invalid_input_errors_no_partial_writes_or_external_redirect(self):
        self.actor(99)
        before=self.rows('SELECT * FROM boards')
        self.assertEqual(self.post('/space/team/901',action='board_archive',board_id='bad').status_code,400)
        self.assertEqual(self.rows('SELECT * FROM boards'),before)
        self.actor(8)
        for payload in ([],None,{'list_id':'bad'},{'list_id':True}):
            self.assertEqual(self.client.post('/space/card/901/move',data=json.dumps(payload),content_type='application/json',headers={'X-CSRF':'synthetic-csrf'}).status_code,400)
        self.assertEqual(self.client.post('/api/chat/send',data='{bad',content_type='application/json',headers={'X-CSRF':'synthetic-csrf'}).status_code,400)
        self.actor(1)
        response=self.client.post('/admin',data={'csrf_token':'synthetic-csrf','form':'user','username':'admin','password':'SyntheticOnly!12345','full_name':'duplicate','email':'synthetic@example.invalid','role':'Requester','structure':'A','sector':'A'},headers={'Referer':'https://evil.invalid/steal'})
        self.assertEqual(response.status_code,302); self.assertFalse(response.location.startswith('http'))
        self.assertEqual(self.rows("SELECT count(*) FROM users WHERE username='admin'"),[(1,)])
        self.assertEqual(self.post('/admin',form='group',name='Synthetic after rollback').status_code,302)

    def test_b07_referenced_user_delete_keeps_chat_and_team_integrity(self):
        self.actor(1)
        before=self.rows('SELECT * FROM chat_messages')
        self.assertEqual(self.post('/users',action='delete',user_id='99').status_code,302)
        self.assertEqual(self.rows('SELECT active FROM users WHERE id=99'),[(0,)])
        self.assertEqual(self.rows('SELECT * FROM chat_messages'),before)
        self.assertEqual(self.rows('SELECT owner_id FROM teams WHERE id=901'),[(99,)])
