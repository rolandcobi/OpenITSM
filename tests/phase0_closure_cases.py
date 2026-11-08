"""Explicit finite acceptance contracts; all fixtures use Phase0HTTP's temporary DB."""
import csv
import io
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import urlencode


class ClosureCases:
    def table_snapshot(self, tables):
        c=self.m.db()
        try: return tuple([tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables)
        finally: c.close()

    def workspace_snapshot(self):
        return self.table_snapshot(('teams','team_members','boards','board_lists','cards'))

    def test_closure_workspace_dispatchers_role_membership_hierarchy_matrix(self):
        team_actions=[('add_member',dict(user_id='50')),('add_sector',dict(sector='Closure sector')),
                      ('remove_member',dict(user_id='50')),('set_role',dict(user_id='50',role='Lead')),
                      ('board_create',dict(name='Closure board')),('board_archive',dict(board_id='910',v='1')),
                      ('team_update',dict(name='Closure changed')),('team_delete',dict(confirm='1'))]
        board_actions=[('list_add',dict(name='Closure list')),('list_delete',dict(list_id='912')),
                       ('card_add',dict(list_id='910',title='Closure added')),('card_update',dict(card_id='910',list_id='911',title='Closure changed')),
                       ('card_delete',dict(card_id='910')),('board_rename',dict(name='Closure changed')),
                       ('board_delete',dict(confirm='1'))]
        count=0
        for mode in ('org','legacy'):
            for uid in range(1,10):
                for relation in ('owner','Lead','Member','Viewer','local_observer','foreign','head_child','personal_owner','personal_foreign'):
                    for endpoint,action,fields in ([('team',a,f) for a,f in team_actions]
                                                   + [('board',a,f) for a,f in board_actions]
                                                   + [('move','move',{}),('done','task_done',{})]):
                        if relation.startswith('personal') and endpoint=='team': continue
                        self.setUp()
                        seed=self.m.db()
                        seed.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
                        seed.execute('UPDATE users SET org_unit_id=2,org_head=? WHERE id=?',(int(relation=='head_child'),uid))
                        seed.execute("INSERT INTO users(id,username,full_name,role,active,org_unit_id,sector) VALUES(50,'closure50','Closure member','Operational Operator',1,2,'Closure sector')")
                        owner=uid if relation in ('owner','personal_owner') else 99
                        seed.execute('UPDATE users SET org_unit_id=? WHERE id=99',(6 if relation=='foreign' else 3 if relation=='head_child' else 2,))
                        seed.execute("INSERT INTO teams(id,name,owner_id) VALUES(910,'Closure team',?)",(owner,))
                        seed.execute("INSERT INTO team_members(team_id,user_id,role) VALUES(910,50,'Member')")
                        if action in ('add_member','add_sector'):
                            seed.execute('DELETE FROM team_members WHERE team_id=910 AND user_id=50')
                        if relation in ('Lead','Member','Viewer'):
                            seed.execute('INSERT INTO team_members(team_id,user_id,role) VALUES(910,?,?)',(uid,relation))
                        team=None if relation.startswith('personal') else 910
                        seed.execute("INSERT INTO boards(id,team_id,name,owner_id) VALUES(910,?,'Closure board',?)",(team,owner))
                        for lid,done in ((910,0),(911,1),(912,0)):
                            seed.execute("INSERT INTO board_lists(id,board_id,name,is_done) VALUES(?,910,?,?)",(lid,'Closure '+str(lid),done))
                        seed.execute("INSERT INTO cards(id,board_id,list_id,title,creator_id,assignee_id) VALUES(910,910,910,'Closure original',?,50)",(owner,))
                        seed.commit(); seed.close()
                        self.actor(uid)
                        writable=relation in ('owner','Lead','Member','personal_owner')
                        manage=relation in ('owner','Lead')
                        if endpoint=='team':
                            allowed=manage
                            changes=allowed and (action!='team_delete' or relation=='owner' or uid in (1,5))
                            path='/space/team/910'
                        else:
                            allowed=writable
                            changes=allowed and (action!='board_delete' or relation=='personal_owner')
                            path='/space/board/910' if endpoint=='board' else '/space/card/910/move' if endpoint=='move' else '/space'
                        before=self.workspace_snapshot()
                        with self.subTest(mode=mode,uid=uid,relation=relation,endpoint=endpoint,action=action):
                            if endpoint=='move':
                                response=self.client.post(path,json={'list_id':911,'pos':0},headers={'X-CSRF':'synthetic-csrf'})
                            else:
                                response=self.post(path,action=action,**(dict(card_id='910') if endpoint=='done' else fields))
                            self.assertEqual(response.status_code,200 if allowed and endpoint=='move' else 302 if allowed else 403)
                            after=self.workspace_snapshot()
                            if changes: self.assertNotEqual(after,before)
                            else: self.assertEqual(after,before)
                            # Every permitted write must leave the unrelated private board untouched.
                            self.assertEqual(self.rows('SELECT title,list_id FROM cards WHERE id=901'),[('PRIVATE_CARD',901)])
                        count+=1
        self.runtime_evidence.append(dict(kind='workspace_action_matrix',cases=count))

    def test_closure_org_dispatchers_all_roles_scope_and_head_matrix(self):
        count=0
        for mode in ('org','legacy'):
            for uid in range(1,10):
                for realm in ('own','child_head','foreign','empty','root_head'):
                    for action in ('unit_add','unit_rename','unit_move','unit_delete','assign_users','service_map','settings'):
                        self.setUp()
                        seed=self.m.db()
                        seed.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
                        parent=6 if realm=='foreign' else 2
                        seed.execute("INSERT INTO org_units(id,parent_id,name) VALUES(910,?,'Closure unit')",(parent,))
                        unit=910 if realm=='own' else None if realm=='empty' else 1 if realm=='root_head' else 2
                        seed.execute('UPDATE users SET org_unit_id=?,org_head=? WHERE id=?',(unit,int(realm in ('child_head','root_head')),uid))
                        # Target unit is initially empty so deletion is independently valid.
                        if action in ('assign_users','service_map'):
                            seed.execute("INSERT INTO users(id,username,full_name,role,active,org_unit_id) VALUES(50,'closure50','Closure user','Requester',1,910)")
                            seed.execute("INSERT INTO services(id,name,unit_id) VALUES(910,'Closure service',910)")
                        seed.commit(); seed.close()
                        self.actor(uid)
                        fields={'unit_add':dict(parent_id='910',name='Closure added'),
                                'unit_rename':dict(id='910',name='Closure changed'),
                                'unit_move':dict(id='910',parent_id='3'),
                                'unit_delete':dict(id='910',confirm='1'),
                                'assign_users':dict(unit_50='3'),
                                'service_map':dict(svc_910='3'),
                                'settings':dict(mode='legacy' if mode=='org' else 'org',confirm='1',intake_unit_id='3')}[action]
                        authorized=uid==1 or uid==5 and realm in ('own','child_head','root_head')
                        if uid==5 and action=='settings': authorized=False
                        if uid==5 and action in ('unit_move','assign_users','service_map') and realm=='own': authorized=False
                        # Bulk maps skip foreign records rather than mutate them.
                        skipped=uid==5 and realm in ('foreign','empty') and action in ('assign_users','service_map')
                        before=self.table_snapshot(('org_units','users','services','settings','tickets'))
                        with self.subTest(mode=mode,uid=uid,realm=realm,action=action):
                            response=self.post('/org',action=action,**fields)
                            self.assertEqual(response.status_code,302 if authorized or skipped else 403)
                            after=self.table_snapshot(('org_units','users','services','settings','tickets'))
                            # A unit containing the actor cannot be deleted.
                            changed=authorized and not (action=='unit_delete' and realm=='own')
                            if changed: self.assertNotEqual(after,before)
                            else: self.assertEqual(after,before)
                        count+=1
        self.runtime_evidence.append(dict(kind='org_action_matrix',cases=count))

    def test_closure_resolved_and_closed_parent_task_lifecycle(self):
        # Preserve the existing contract: Resolved is reversible and permits staff
        # work; it does not silently change ticket status. Closed is immutable.
        for mode in ('org','legacy'):
            for uid in range(1,10):
                for state in ('Resolved','Closed'):
                    self.setUp()
                    self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
                    self.execute('UPDATE tickets SET status=?,assignee_id=4 WHERE id=101',(state,))
                    self.execute("UPDATE tasks SET status='Completed',completed_at='2026-11-04 12:00:00' WHERE id=101")
                    self.execute('INSERT INTO task_assignees VALUES(101,4)')
                    self.actor(uid)
                    before=self.rows('SELECT * FROM tasks ORDER BY id')
                    response=self.post('/tasks/101/do',action='reopen',note='Closure lifecycle evidence')
                    allowed=uid in (1,2,3,4,5,6) and state=='Resolved'
                    self.assertEqual(response.status_code,302 if allowed else 403)
                    self.assertEqual(self.rows('SELECT status FROM tasks WHERE id=101'),[('In Progress' if allowed else 'Completed',)])
                    self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[(state,)])
                    if not allowed: self.assertEqual(self.rows('SELECT * FROM tasks ORDER BY id'),before)
                    count=self.rows('SELECT count(*) FROM tasks')[0][0]
                    response=self.post('/tickets/101',action='task',task_title='Closure new task',task_assignees='4')
                    self.assertEqual(response.status_code,302 if allowed else 403)
                    self.assertEqual(self.rows('SELECT count(*) FROM tasks')[0][0],count+int(allowed))
                    self.assertEqual(self.rows('SELECT status FROM tickets WHERE id=101'),[(state,)])

    def export_cells(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        if '/csv' in path:
            return list(csv.reader(io.StringIO(response.data.decode('utf-8-sig')), delimiter=';'))
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        self.assertEqual(root.findall('.//m:f', ns), [])
        return [[self.m._csv_safe(''.join(c.itertext())) if c.get('t') == 'inlineStr'
                 else c.findtext('m:v', '', ns) for c in row.findall('m:c', ns)]
                for row in root.findall('.//m:row', ns)]

    def test_closure_summary_all_roles_modes_mixed_filters_exact_content(self):
        # Independent expected aggregates use synthetic records, not exporter helpers.
        self.execute("UPDATE tickets SET assignee_id=4 WHERE id=101")
        self.execute("UPDATE tickets SET created_at='2020-01-01 00:00:00',status='Resolved',type='Task',priority='High' WHERE id=102")
        samples = [dict(code='SYN-101', date='2026-11-04', status='Open', type='Service Request',
                        priority='Medium', assignee='Synthetic Operational Operator', unit=2),
                   dict(code='SYN-102', date='2020-01-01', status='Resolved', type='Task',
                        priority='High', assignee='-', unit=6)]
        filters = [{}, {'status':'Open'}, {'status':'Resolved'}, {'type':'Task'},
                   {'date_from':'2026-01-01','date_to':'2026-12-31','status':'Open','type':'Service Request'},
                   {'date_to':'2020-01-01','type':'Task','status':'Resolved'},
                   {'date_from':'2099-01-01'}, {'date_from':'2026-11-04','date_to':'2026-11-04'},
                   {'date_from':'2027-01-01','date_to':'2020-01-01'}]
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'", (mode,))
            for uid in range(1,10):
                self.actor(uid)
                for fl in filters:
                    with self.subTest(mode=mode, uid=uid, filters=fl):
                        selected=[r for r in reversed(samples) if (uid==1 or uid!=9 and r['unit']==2)
                                  and all(not fl.get(k) or r[k]==fl[k] for k in ('status','type'))
                                  and (not fl.get('date_from') or r['date']>=fl['date_from'])
                                  and (not fl.get('date_to') or r['date']<=fl['date_to'])]
                        expected=[['Summary','Total tickets',str(len(selected))]]
                        for label,key in (('By status','status'),('By type','type'),
                                          ('By priority','priority'),('By SLA','sla'),('By assignee','assignee')):
                            counts=Counter(r.get(key,'-') for r in selected)
                            expected += [[label,self.m._csv_safe(k),str(v)] for k,v in counts.most_common()]
                        for fmt in ('csv','xlsx'):
                            rows=self.export_cells('/reports/export/summary/'+fmt+'?'+urlencode(fl))
                            self.assertEqual(rows[0],['Seksioni','Treguesi','Vlera'])
                            self.assertEqual(rows[1:],expected)

    def test_closure_audit_all_roles_modes_mixed_filters_xlsx_pagination(self):
        from flask import template_rendered
        # 105 local + 3 foreign events crosses the page boundary. Explicit IDs avoid
        # export-generated audit events and make the expected ordering independent.
        events=[]
        for i in range(108):
            local=i<105
            event=dict(id=300000+i, actor=1 if i%2==0 else 5,
                       action='ClosureA' if i%3==0 else 'ClosureB',
                       obj='Ticket', oid=101 if local else 102,
                       date='2026-11-04' if i%2==0 else '2026-11-05',
                       old='=old'+str(i), new='Closure evidence '+str(i), ip='127.0.0.1')
            events.append(event)
            self.execute('INSERT INTO audit(id,actor_id,action,object_type,object_id,old_value,new_value,ip,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (event['id'],event['actor'],event['action'],event['obj'],event['oid'],event['old'],event['new'],event['ip'],event['date']+' 10:00:00'))
        filters=[{}, {'action':'ClosureA'}, {'actor':'5'}, {'obj':'Ticket'},
                 {'date_from':'2026-11-05','date_to':'2026-11-05','actor':'5','action':'ClosureB','obj':'Ticket'},
                 {'date_to':'2026-11-04','actor':'1','action':'ClosureA'},
                 {'date_from':'2099-01-01'}, {'actor':'none'}, {'obj':'Asset'}]
        for mode in ('org','legacy'):
            self.execute("UPDATE settings SET value=? WHERE key='visibility_mode'",(mode,))
            for uid in range(1,10):
                self.actor(uid)
                for fl in filters:
                    query=urlencode(dict(q='Closure evidence',**fl))
                    with self.subTest(mode=mode,uid=uid,filters=fl):
                        if uid not in (1,5,7,9):
                            for path in ('/audit?','/audit/export/csv?','/audit/export/xlsx?'):
                                self.assertEqual(self.client.get(path+query).status_code,403)
                            continue
                        selected=[r for r in reversed(events) if (uid==1 or r['oid']==101)
                                  and (not fl.get('action') or r['action']==fl['action'])
                                  and (not fl.get('obj') or r['obj']==fl['obj'])
                                  and (not fl.get('actor') or str(r['actor'])==fl['actor'])
                                  and (not fl.get('date_from') or r['date']>=fl['date_from'])
                                  and (not fl.get('date_to') or r['date']<=fl['date_to'])]
                        expected=[[str(r['id']),r['date']+' 10:00:00',
                                   'System Administrator' if r['actor']==1 else 'Synthetic Central Administrator',
                                   'admin' if r['actor']==1 else 'synthetic5',r['action'],r['obj'],str(r['oid']),
                                   "'"+r['old'],r['new'],r['ip']] for r in selected]
                        # Bootstrap display name is a fixture value, not a role label.
                        admin_name=self.rows('SELECT full_name FROM users WHERE id=1')[0][0]
                        for row in expected:
                            if row[3]=='admin': row[2]=admin_name
                        for fmt in ('csv','xlsx'):
                            actual=self.export_cells('/audit/export/'+fmt+'?'+query)
                            self.assertEqual(len(actual[0]),10)
                            self.assertEqual(actual[1:],expected)
                        for page in (1,2,3):
                            contexts=[]
                            def capture(sender,template,context,**extra): contexts.append(context)
                            with template_rendered.connected_to(capture,self.m.app):
                                response=self.client.get('/audit?'+query+'&page='+str(page))
                            self.assertEqual(response.status_code,200)
                            context=contexts[-1]
                            self.assertEqual(context['total'],len(selected))
                            self.assertEqual([r['id'] for r in context['rows']],
                                             [r['id'] for r in selected[(page-1)*100:page*100]])
