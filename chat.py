"""Internal one-to-one chat between active users with polling notifications."""
import time
from authorization import directory_scope_sql
from collections import defaultdict, deque
from flask import request, jsonify
SCHEMA="""CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY,from_id INTEGER NOT NULL,to_id INTEGER NOT NULL,body TEXT NOT NULL,created_at TEXT,read_at TEXT);
CREATE INDEX IF NOT EXISTS ix_chat_to ON chat_messages(to_id,id);CREATE INDEX IF NOT EXISTS ix_chat_pair ON chat_messages(from_id,to_id,id);"""
def init(app,D):
    db,login_required,current,now=D['db'],D['login_required'],D['current'],D['now']
    RATE=defaultdict(deque)
    def sub(r): return ' · '.join(x for x in (r['duty'],r['sector'],r['institution']) if x)
    def msg(r): return dict(id=r['id'],from_id=r['from_id'],to_id=r['to_id'],body=r['body'],at=(r['created_at'] or '')[:16])
    def partner(c,pid):
        if not str(pid or '').isdigit(): return None
        scope,args=directory_scope_sql(current(),D.get('org'),c); me=current()['id']
        return c.execute('SELECT u.id,u.full_name,u.duty,u.sector,u.institution FROM users u WHERE u.id=? AND u.active=1 AND ('+scope+' OR EXISTS(SELECT 1 FROM chat_messages m WHERE (m.from_id=? AND m.to_id=u.id) OR (m.to_id=? AND m.from_id=u.id)))',[int(pid),*args,me,me]).fetchone()
    @app.get('/api/chat/state')
    @login_required
    def chat_state():
        u=current(); c=db(); me=u['id']
        rows=c.execute('''SELECT p.id,p.full_name,p.duty,p.sector,p.institution,m.body last_body,m.created_at last_at,m.from_id last_from,
            (SELECT count(*) FROM chat_messages x WHERE x.from_id=p.id AND x.to_id=? AND x.read_at IS NULL) unread
            FROM users p JOIN chat_messages m ON m.id=(SELECT max(id) FROM chat_messages y WHERE (y.from_id=p.id AND y.to_id=?) OR (y.from_id=? AND y.to_id=p.id))
            WHERE p.active=1 AND p.id!=? ORDER BY m.id DESC LIMIT 40''',(me,me,me,me)).fetchall()
        tot=c.execute('SELECT count(*) FROM chat_messages WHERE to_id=? AND read_at IS NULL',(me,)).fetchone()[0]; last=c.execute('SELECT COALESCE(max(id),0) FROM chat_messages WHERE to_id=?',(me,)).fetchone()[0]; c.close()
        return jsonify(unread=tot,last_in=last,convs=[dict(id=r['id'],name=r['full_name'],sub=sub(r),last=(r['last_body'] or '')[:80],at=(r['last_at'] or '')[:16],mine=r['last_from']==me,unread=r['unread']) for r in rows])
    @app.get('/api/chat/poll')
    @login_required
    def chat_poll():
        me=current()['id']; after=int(request.args.get('after')) if (request.args.get('after') or '').isdigit() else 0; c=db()
        rows=c.execute('SELECT m.*,u.full_name fname FROM chat_messages m JOIN users u ON u.id=m.from_id WHERE m.to_id=? AND m.id>? ORDER BY m.id LIMIT 20',(me,after)).fetchall()
        tot=c.execute('SELECT count(*) FROM chat_messages WHERE to_id=? AND read_at IS NULL',(me,)).fetchone()[0]; c.close()
        return jsonify(unread=tot,new=[dict(msg(r),name=r['fname']) for r in rows])
    @app.get('/api/chat/thread')
    @login_required
    def chat_thread():
        me=current()['id']; c=db(); p=partner(c,request.args.get('with'))
        if not p or p['id']==me: c.close(); return jsonify(error='User not found'),404
        after=int(request.args.get('after')) if (request.args.get('after') or '').isdigit() else 0
        rows=c.execute('SELECT * FROM (SELECT * FROM chat_messages WHERE ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?)) AND id>? ORDER BY id DESC LIMIT 80) ORDER BY id',(me,p['id'],p['id'],me,after)).fetchall()
        c.close()
        return jsonify(user=dict(id=p['id'],name=p['full_name'],sub=sub(p)),messages=[msg(r) for r in rows])
    @app.post('/api/chat/read')
    @login_required
    def chat_read():
        j=request.get_json(silent=True)
        if not isinstance(j,dict): return jsonify(error='Invalid JSON object'),400
        c=db(); p=partner(c,j.get('with')); me=current()['id']
        if not p or p['id']==me: c.close(); return jsonify(error='Invalid partner'),400
        c.execute('UPDATE chat_messages SET read_at=? WHERE to_id=? AND from_id=? AND read_at IS NULL',(now(),me,p['id']))
        c.commit(); c.close(); return jsonify(ok=True)
    @app.post('/api/chat/send')
    @login_required
    def chat_send():
        me=current()['id']; j=request.get_json(silent=True)
        if not isinstance(j,dict): return jsonify(error='Invalid JSON object'),400
        body=str(j.get('body') or '').strip()[:2000]
        q=RATE[me]; t=time.time()
        while q and t-q[0]>10: q.popleft()
        if len(q)>=20: return jsonify(error='Too many messages; please wait.'),429
        c=db(); p=partner(c,j.get('to'))
        if not p or p['id']==me: c.close(); return jsonify(error='User not found'),404
        if not body: c.close(); return jsonify(error='Message is empty'),400
        q.append(t); mid=c.execute('INSERT INTO chat_messages(from_id,to_id,body,created_at) VALUES(?,?,?,?)',(me,p['id'],body,now())).lastrowid; c.commit()
        r=c.execute('SELECT * FROM chat_messages WHERE id=?',(mid,)).fetchone(); c.close(); return jsonify(message=msg(r)),201
