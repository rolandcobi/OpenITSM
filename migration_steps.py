"""Ordered schema-v1 steps; callers must supply the transaction-safe connection."""
from werkzeug.security import generate_password_hash
from org import SCHEMA as ORG_SCHEMA, TREE, SVC_MAP
from space import SCHEMA as SPACE_SCHEMA
from chat import SCHEMA as CHAT_SCHEMA

def cols(c,t): return [r['name'] for r in c.execute(f'PRAGMA table_info({t})')]

def init_db(c,bootstrap_password):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,full_name TEXT,email TEXT,role TEXT,structure TEXT,sector TEXT,active INTEGER DEFAULT 1);
 CREATE TABLE IF NOT EXISTS support_groups(id INTEGER PRIMARY KEY,name TEXT UNIQUE,description TEXT);
 CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY,name TEXT UNIQUE,category TEXT,status TEXT DEFAULT 'Operational',owner_id INTEGER);
 CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY,name TEXT NOT NULL,asset_type TEXT,hostname TEXT,ip_address TEXT,service_id INTEGER,structure TEXT,location TEXT,owner_id INTEGER,criticality TEXT DEFAULT 'Medium',status TEXT DEFAULT 'Operational',notes TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY,code TEXT UNIQUE,type TEXT,title TEXT,description TEXT,category TEXT,service_id INTEGER,structure TEXT,priority TEXT,status TEXT,requester_id INTEGER,assignee_id INTEGER,created_by INTEGER,created_at TEXT,due_at TEXT,resolved_at TEXT,closed_at TEXT);
 CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,ticket_id INTEGER,title TEXT,description TEXT,group_id INTEGER,priority TEXT,status TEXT DEFAULT 'Open',due_at TEXT,created_at TEXT,completed_at TEXT,completion_notes TEXT);
 CREATE TABLE IF NOT EXISTS task_assignees(task_id INTEGER,user_id INTEGER,PRIMARY KEY(task_id,user_id));
 CREATE TABLE IF NOT EXISTS timeline(id INTEGER PRIMARY KEY,ticket_id INTEGER,actor_id INTEGER,event_type TEXT,details TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor_id INTEGER,action TEXT,object_type TEXT,object_id INTEGER,old_value TEXT,new_value TEXT,ip TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
 CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT,attempted_at REAL);
 CREATE INDEX IF NOT EXISTS ix_login_attempts ON login_attempts(ip,attempted_at);
 CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT,message TEXT,link TEXT,kind TEXT DEFAULT 'info',is_read INTEGER DEFAULT 0,created_at TEXT);
 CREATE TABLE IF NOT EXISTS ticket_steps(id INTEGER PRIMARY KEY,ticket_id INTEGER,seq INTEGER,user_id INTEGER,instruction TEXT,status TEXT DEFAULT 'Pending',note TEXT,signed_by TEXT,signed_at TEXT,activated_at TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS email_log(id INTEGER PRIMARY KEY,to_addr TEXT,subject TEXT,ok INTEGER,message TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS task_events(id INTEGER PRIMARY KEY,task_id INTEGER,actor_id INTEGER,event_type TEXT,details TEXT,created_at TEXT);
 CREATE INDEX IF NOT EXISTS idx_task_events ON task_events(task_id);
 CREATE INDEX IF NOT EXISTS ix_tk_status ON tickets(status,created_at);
 CREATE INDEX IF NOT EXISTS ix_tk_assignee ON tickets(assignee_id,status);
 CREATE INDEX IF NOT EXISTS ix_tk_requester ON tickets(requester_id);
 CREATE INDEX IF NOT EXISTS ix_tk_due ON tickets(due_at);
 CREATE INDEX IF NOT EXISTS ix_tk_service ON tickets(service_id);
 CREATE INDEX IF NOT EXISTS ix_tl_ticket ON timeline(ticket_id,id);
 CREATE INDEX IF NOT EXISTS ix_tasks_ticket ON tasks(ticket_id,status);
 CREATE INDEX IF NOT EXISTS ix_ta_user ON task_assignees(user_id);
 CREATE INDEX IF NOT EXISTS ix_steps_ticket ON ticket_steps(ticket_id,seq);
 CREATE INDEX IF NOT EXISTS ix_steps_user ON ticket_steps(user_id,status);
 CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id,is_read,id);
 CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY,title TEXT,message TEXT,kind TEXT,created_by INTEGER,created_at TEXT,active INTEGER DEFAULT 1);
 CREATE TRIGGER IF NOT EXISTS audit_nu BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit është i pandryshueshëm'); END;
 CREATE TRIGGER IF NOT EXISTS audit_nd BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit është i pandryshueshëm'); END;
 ''')
 # migrate older MVP safely
 for table,name,definition in [('users','sector','TEXT'),('services','owner_id','INTEGER'),('tasks','group_id','INTEGER'),('users','auth_version','INTEGER NOT NULL DEFAULT 0'),('users','failed','INTEGER DEFAULT 0'),('users','locked_until','TEXT'),('users','must_change','INTEGER DEFAULT 0'),('users','can_infra','INTEGER DEFAULT 0'),('users','phone','TEXT'),('users','institution','TEXT'),('users','duty','TEXT'),('users','profile_done','INTEGER DEFAULT 0'),('tasks','parent_id','INTEGER'),('tasks','created_by','INTEGER'),('tasks','started_at','TEXT'),('tickets','resolution_note','TEXT')]:
  if name not in cols(c,table): c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
 if not c.execute('SELECT 1 FROM users').fetchone():
  _pw=bootstrap_password;
  if len(_pw)<12: raise RuntimeError('First start requires ITSM_INITIAL_ADMIN_PASSWORD with at least 12 characters. See README.md.')
  c.execute('INSERT INTO users(username,password_hash,full_name,email,role,structure,sector) VALUES(?,?,?,?,?,?,?)',('admin',generate_password_hash(_pw),'System Administrator','admin@localhost','System Administrator','Example Organization','IT Administration'))
 if not c.execute('SELECT 1 FROM support_groups').fetchone():
  for n in ['Service Desk','Network Administration','Systems Administration','Messaging Administration','Security Operations']: c.execute('INSERT OR IGNORE INTO support_groups(name) VALUES(?)',(n,))
 # Official Service Catalog v8.3: exactly 10 main services. Any additional service is a subsection.
 if 'parent_service_id' not in cols(c,'services'): c.execute('ALTER TABLE services ADD COLUMN parent_service_id INTEGER')
 if 'is_main' not in cols(c,'services'): c.execute('ALTER TABLE services ADD COLUMN is_main INTEGER DEFAULT 0')
 # Configurable sample catalog; never overwrite or reset user-defined services.
 default_services=[('Network Connectivity','Network'),('Email & Collaboration','Messaging'),('Identity & Access','Identity'),('Endpoint Protection','Security'),('Security Monitoring','Security'),('Backup & Recovery','Recovery')]
 if not c.execute('SELECT 1 FROM services').fetchone():
  for name,category in default_services:
   c.execute('INSERT INTO services(name,category,is_main) VALUES(?,?,1)',(name,category))

def organization(c):
    c.executescript(ORG_SCHEMA)
    migrate_assets = 'unit_id' not in [r['name'] for r in c.execute('PRAGMA table_info(assets)')]
    for t,col,df in (('users','org_unit_id','INTEGER'),('users','org_head','INTEGER DEFAULT 0'),('tickets','unit_id','INTEGER'),('services','unit_id','INTEGER'),('assets','unit_id','INTEGER')):
        if col not in [r['name'] for r in c.execute(f'PRAGMA table_info({t})')]: c.execute(f'ALTER TABLE {t} ADD COLUMN {col} {df}')
    c.execute('CREATE INDEX IF NOT EXISTS ix_tk_unit ON tickets(unit_id)'); c.execute('CREATE INDEX IF NOT EXISTS ix_users_unit ON users(org_unit_id)')
    if not c.execute('SELECT 1 FROM org_units').fetchone():
        rid=c.execute("INSERT INTO org_units(parent_id,name,kind,sort) VALUES(NULL,?,?,0)",(TREE[0],TREE[1])).lastrowid
        for i,(un,uk,secs) in enumerate(TREE[2]):
            uid=c.execute("INSERT INTO org_units(parent_id,name,kind,sort) VALUES(?,?,?,?)",(rid,un,uk,i)).lastrowid
            for j,s in enumerate(secs): c.execute("INSERT INTO org_units(parent_id,name,kind,sort) VALUES(?,?,'SECTOR',?)",(uid,s,j))
        for sn,un in SVC_MAP.items():
            u=c.execute('SELECT id FROM org_units WHERE name=?',(un,)).fetchone(); c.execute('UPDATE services SET unit_id=? WHERE name=? AND unit_id IS NULL',(u['id'],sn))
        h=c.execute("SELECT id FROM org_units WHERE name='Service Desk'").fetchone()
        if h: c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('intake_unit_id',?)",(str(h['id']),))
    if migrate_assets:
        # Only unambiguous validated owner/service unit IDs may classify old assets.
        # Free-text structure never grants access; conflicting/missing scope stays NULL.
        c.execute('''UPDATE assets SET unit_id=(
            SELECT COALESCE(s.unit_id,u.org_unit_id)
            FROM (SELECT 1) seed
            LEFT JOIN services s ON s.id=assets.service_id
            LEFT JOIN users u ON u.id=assets.owner_id
            WHERE (s.unit_id IS NULL OR u.org_unit_id IS NULL OR s.unit_id=u.org_unit_id)
            AND EXISTS(SELECT 1 FROM org_units o WHERE o.id=COALESCE(s.unit_id,u.org_unit_id)))''')
    c.execute('CREATE INDEX IF NOT EXISTS ix_assets_unit ON assets(unit_id)')

def workspace(c):
    c.executescript(SPACE_SCHEMA); cc = [r['name'] for r in c.execute('PRAGMA table_info(cards)')]
    if 'source' not in cc: c.execute("ALTER TABLE cards ADD COLUMN source TEXT DEFAULT 'Personal Initiative'")
    if 'source_ref' not in cc: c.execute('ALTER TABLE cards ADD COLUMN source_ref TEXT')

def chat(c):
    c.executescript(CHAT_SCHEMA)
