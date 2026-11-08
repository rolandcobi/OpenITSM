"""English UI contracts with disposable synthetic databases only."""
import ast
import re
import tempfile
import time
import unittest
from pathlib import Path
from application import create_app

ROOT=Path(__file__).resolve().parents[1]

class EnglishUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='openitsm-english-')
        self.folder=Path(self.temp.name)
        self.app=create_app(dict(ITSM_ENV='test',ITSM_DB=str(self.folder/'synthetic.sqlite'),
            ITSM_SECRET_KEY='synthetic-english-secret-'*3,ITSM_INITIAL_ADMIN_PASSWORD='SyntheticOnly!12345',
            ITSM_TLS='1',ITSM_HTTPS='0',ITSM_BACKUP='0',TESTING=True),environ={},
            start_workers=False,backup_dir=self.folder/'backups')
        self.runtime=self.app.extensions['openitsm']['runtime']
        c=self.runtime.db()
        c.execute('UPDATE users SET profile_done=1,must_change=0 WHERE id=1')
        c.execute("INSERT INTO users(id,username,full_name,role,org_unit_id,profile_done) VALUES(101,'synthetic-reader','Synthetic reader','Requester',2,1)")
        c.execute("INSERT INTO tickets(id,code,type,title,description,status,priority,requester_id,created_by,unit_id,created_at) VALUES(101,'SYN-EN-101','Service Request','Synthetic English ticket','Synthetic details','Open','Medium',101,1,2,'2026-11-04 10:00:00')")
        c.execute("INSERT INTO tasks(id,ticket_id,title,status,created_at,created_by) VALUES(101,101,'Synthetic task','Open','2026-11-04 10:00:00',1)")
        c.execute("INSERT INTO teams(id,name,owner_id,created_at) VALUES(101,'Synthetic team',1,'2026-11-04 10:00:00')")
        c.execute("INSERT INTO team_members(team_id,user_id,role,added_at) VALUES(101,1,'Lead','2026-11-04 10:00:00')")
        c.execute("INSERT INTO boards(id,team_id,owner_id,name,created_at) VALUES(101,101,1,'Synthetic board','2026-11-04 10:00:00')")
        c.commit();c.close()
        self.client=self.app.test_client()
        self.actor()

    def tearDown(self): self.temp.cleanup()

    def actor(self,uid=1):
        with self.client.session_transaction() as s:
            s.clear();s.update(uid=uid,auth_version=0,issued_at=time.time(),csrf='synthetic-english-csrf',name='Synthetic user',role='System Administrator' if uid==1 else 'Requester')

    def test_all_module_pages_render_english_headings(self):
        pages={'/':'Dashboard','/account':'My account','/admin':'Administration',
            '/assets':'CMDB &amp; Assets','/audit':'Audit Log','/calendar':'Ticket and task calendar',
            '/directory':'User directory','/notifications':'Notification center','/org':'Organizational structure',
            '/profile':'My profile','/reports':'Reports &amp; KPIs','/services':'Service Catalog',
            '/space':'My workspace','/space/team/101':'Synthetic team','/space/team/101/dashboard':'Performance',
            '/space/board/101':'Synthetic board','/tasks':'Tasks','/tasks/101':'Details',
            '/tickets':'Monitoring &amp; Operations','/tickets/101':'Details','/tickets/new':'Create Ticket','/users':'User management'}
        for path,text in pages.items():
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                body=response.get_data(as_text=True)
                self.assertIn(text,body.replace('&','&amp;') if '&amp;' in text else body)
                self.assertIn('lang="en"',body)

    def test_requester_pages_keep_scope_and_english_forms(self):
        self.actor(101)
        for path,text in [('/tickets/101','Required action'),('/tickets/new','SLA (working hours)'),('/profile','Position')]:
            with self.subTest(path=path):
                r=self.client.get(path);self.assertEqual(r.status_code,200);self.assertIn(text,r.get_data(as_text=True))
        self.assertEqual(self.client.get('/admin').status_code,403)

    def test_csrf_error_and_invalid_login_are_english(self):
        r=self.client.post('/tickets/101',data={'action':'status','status':'Closed'})
        self.assertEqual(r.status_code,403);self.assertIn('Invalid CSRF token',r.get_data(as_text=True))
        self.client.get('/logout')
        with self.client.session_transaction() as s:s.clear()
        self.client.get('/login')
        with self.client.session_transaction() as s:token=s['csrf']
        r=self.client.post('/login',data={'username':'not-a-user','password':'SyntheticWrong!123','csrf_token':token})
        self.assertIn('Invalid credentials.',r.get_data(as_text=True))

    def test_calendar_month_and_weekdays_are_english(self):
        import datetime
        offset=3-datetime.datetime.now().month
        r=self.client.get('/calendar?offset='+str(offset))
        text=r.get_data(as_text=True)
        for word in ('March','Mon','Tue','Wed','Thu','Fri','Sat','Sun'):self.assertIn(word,text)
        self.assertNotIn('Tuech',text)

    def test_email_text_html_and_escaping(self):
        text,html=self.runtime.render_mail('Ticket assigned','Hello Synthetic reader',
            [('Priority','HIGH')],'Synthetic <script>','https://example.invalid/tickets/101','Open ticket')
        for body in (text,html):
            self.assertIn('This is an automated message from OpenITSM.',body)
            self.assertIn('Description',body)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertEqual(self.runtime.send_email('synthetic@example.invalid','Synthetic test','Synthetic body'),(False,'SMTP is not configured.'))

    def test_exports_have_english_headers_and_summary(self):
        for path,expected in [('/reports/export/tickets/csv','Title'),('/reports/export/tasks/csv','Completion notes'),('/reports/export/summary/csv','Summary')]:
            with self.subTest(path=path):
                r=self.client.get(path);self.assertEqual(r.status_code,200);self.assertIn(expected,r.get_data(as_text=True))

    def test_templates_and_javascript_have_no_remaining_albanian_ui_markers(self):
        from jinja2 import Environment
        for path in (ROOT/'templates').glob('*.html'):
            with self.subTest(path=path.name):
                source=path.read_text(encoding='utf-8')
                for _,kind,value in Environment().lex(source):
                    if kind in ('data','string'):
                        self.assertIsNone(re.search(r'[\u00eb\u00e7\u00cb\u00c7]|\b(?:Rikthe|Arkivo|Qendra|Ticket-et|Vonuar|Rihapur|shtuar|enkriptim|Detajet)\b',value),path.name)
                self.assertNotRegex(source,r'Tuek|Tuech|Frivious|Fripare|Nj\?sia|Sh\?no')
        for path in (ROOT/'static').glob('*.js'):
            source='\n'.join(line.split('//')[0] for line in path.read_text(encoding='utf-8').splitlines() if not line.strip().startswith(('/*','*')))
            self.assertIsNone(re.search(r'[\u00eb\u00e7\u00cb\u00c7]',source),path.name)
