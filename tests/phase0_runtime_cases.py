"""Loopback-only production-stack, SMTP and real Chromium browser checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch


def certificate(folder):
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
          .sign(key,hashes.SHA256()))
    certfile=Path(folder)/'synthetic-cert.pem'; keyfile=Path(folder)/'synthetic-key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return str(certfile),str(keyfile)


def tls_server(app,cert,key,threads):
    from cheroot.wsgi import Server
    from cheroot.ssl.builtin import BuiltinSSLAdapter
    server=Server(('127.0.0.1',0),app,numthreads=threads,timeout=5)
    server.ssl_adapter=BuiltinSSLAdapter(cert,key)
    server.ssl_adapter.context.minimum_version=ssl.TLSVersion.TLSv1_2
    server.prepare()
    port=server.socket.getsockname()[1]
    thread=threading.Thread(target=server.serve,daemon=True); thread.start()
    return server,thread,port


class RuntimeCases:
    def test_b08_real_tls_thread_workers_preserve_scope(self):
        with tempfile.TemporaryDirectory(prefix='openitsm-tls-') as tmp:
            cert,key=certificate(tmp); context=ssl.create_default_context(cafile=cert)
            cookie=self.m.app.session_interface.get_signing_serializer(self.m.app).dumps(dict(uid=8,role='Requester',name='Synthetic',csrf='synthetic-csrf',auth_version=0,issued_at=time.time(),_permanent=True))
            with patch.dict(self.m.app.config,SESSION_COOKIE_SECURE=True):
                for workers in (1,4,16):
                    with self.subTest(threads=workers):
                        server,thread,port=tls_server(self.m.app,cert,key,workers)
                        try:
                            def fetch(index):
                                tid=101 if index%2==0 else 102
                                request=urllib.request.Request('https://127.0.0.1:'+str(port)+'/tickets/'+str(tid),headers={'Cookie':'session='+cookie})
                                try:
                                    with urllib.request.urlopen(request,context=context,timeout=15) as response:
                                        self.assertIn('TLS',response.fp.raw._sock.version())
                                        return response.status,response.read()
                                except urllib.error.HTTPError as error: return error.code,error.read()
                            with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(fetch,range(16)))
                            self.assertEqual([r[0] for r in results],[200,403]*8)
                            self.assertTrue(all(b'SECRET_102' not in body for _,body in results))
                            self.runtime_evidence.append(dict(kind='tls_workers',threads=workers,requests=16,allowed=8,denied=8,certificate_verified=True))
                            request=urllib.request.Request('https://127.0.0.1:'+str(port)+'/account',headers={'Cookie':'session='+cookie})
                            with urllib.request.urlopen(request,context=context,timeout=10) as response:
                                self.assertIn('Secure',response.headers['Set-Cookie']); self.assertIn('HttpOnly',response.headers['Set-Cookie'])
                                self.assertIn('SameSite=Lax',response.headers['Set-Cookie']); self.assertIn('max-age=',response.headers['Strict-Transport-Security'])
                        finally: server.stop(); thread.join(timeout=5)

    def test_b08_controlled_tls_smtp_success_and_failure(self):
        delivered=[]; state={'fail':False}
        class SMTP(socketserver.StreamRequestHandler):
            def send(self,line): self.wfile.write((line+'\r\n').encode()); self.wfile.flush()
            def handle(self):
                self.send('220 localhost Synthetic SMTP')
                while True:
                    raw=self.rfile.readline()
                    if not raw: return
                    command=raw.decode(errors='replace').strip().upper()
                    if command.startswith(('EHLO','HELO')): self.send('250 localhost')
                    elif command.startswith('RCPT'): self.send('550 synthetic refusal' if state['fail'] else '250 accepted')
                    elif command=='DATA':
                        self.send('354 send data'); lines=[]
                        while True:
                            line=self.rfile.readline()
                            if not line or line==b'.\r\n': break
                            lines.append(line)
                        delivered.append(b''.join(lines)); self.send('250 queued')
                    elif command=='QUIT': self.send('221 bye'); return
                    else: self.send('250 ok')
        with tempfile.TemporaryDirectory(prefix='openitsm-smtp-') as tmp:
            cert,key=certificate(tmp); server=socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTP)
            server.daemon_threads=True
            server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); server_context.minimum_version=ssl.TLSVersion.TLSv1_2
            server_context.load_cert_chain(cert,key); server.socket=server_context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                for name,value in {'smtp_host':'127.0.0.1','smtp_port':str(server.server_address[1]),'smtp_security':'ssl','smtp_verify':'1','smtp_sender':'synthetic@example.invalid'}.items():
                    self.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(name,value))
                real_context=ssl.create_default_context
                with patch.object(self.m.ssl,'create_default_context',side_effect=lambda:real_context(cafile=cert)),patch.object(self.m,'send_email',side_effect=self.real_send_email):
                    self.actor(1)
                    self.assertEqual(self.post('/admin/test-email',to='synthetic@example.invalid').status_code,302)
                    self.assertEqual(self.rows('SELECT ok FROM email_log ORDER BY id DESC LIMIT 1'),[(1,)])
                    state['fail']=True
                    self.assertEqual(self.post('/admin/test-email',to='synthetic@example.invalid').status_code,302)
                    self.assertEqual(self.rows('SELECT ok FROM email_log ORDER BY id DESC LIMIT 1'),[(0,)])
                    state['fail']=False
                    self.real_send_async('synthetic@example.invalid','Synthetic background','Synthetic body')
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline and len(delivered)<2: threading.Event().wait(0.05)
                    self.assertEqual(len(delivered),2)
                self.runtime_evidence.append(dict(kind='smtp_tls',accepted=2,refused=1,background=True,certificate_verified=True))
                self.assertIn(b'synthetic@example.invalid',delivered[0])
            finally: server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_b08_edge_and_chrome_real_browser_csrf_cookie_and_read_flows(self):
        from werkzeug.wrappers import Response
        browsers={
            'Edge':Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),
            'Chrome':Path('C:/Program Files/Google/Chrome/Application/chrome.exe')}
        driver=r"""
        (async()=>{try{
          const check=(value,message)=>{if(!value)throw Error(message)};
          const get=async path=>fetch(path,{credentials:'same-origin'});
          const post=async(path,body,token='browser-csrf')=>fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF':token},body:JSON.stringify(body)});
          check(!document.cookie.includes('session='),'HttpOnly session visible');
          await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/chat.js';script.onload=resolve;script.onerror=reject;document.head.appendChild(script)});
          const waitFor=async predicate=>{for(let i=0;i<80;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,25))}throw Error('UI did not settle')};
          check((await(await get('/api/poll')).json()).unread===1,'initial unread');
          await get('/notifications'); await fetch('/notifications',{method:'HEAD'});
          check((await(await get('/api/poll')).json()).unread===1,'GET/HEAD changed state');
          check((await post('/notifications/read',{},'wrong')).status===403,'bad CSRF accepted');
          try{await fetch('https://localhost:'+location.port+'/notifications/read',{method:'POST',mode:'no-cors',credentials:'include',body:'csrf_token=wrong'})}catch(e){}
          check((await(await get('/api/poll')).json()).unread===1,'cross-origin state mutation');
          const html=await(await get('/notifications')).text();
          const page=new DOMParser().parseFromString(html,'text/html');
          const form=page.querySelector('form[action="/notifications/read"]');
          check(!!form,'read form missing');
          await fetch(form.getAttribute('action'),{method:'POST',credentials:'same-origin',body:new URLSearchParams(new FormData(form))});
          check((await(await get('/api/poll')).json()).unread===0,'form did not acknowledge');
          await get('/api/chat/thread?with=2');
          check((await(await get('/api/chat/state')).json()).unread===1,'chat GET changed state');
          document.querySelector('#chatRoot .chat-btn').click();
          await waitFor(()=>document.querySelector('#chatRoot .chat-conv'));
          document.querySelector('#chatRoot .chat-conv').click();
          await waitFor(()=>document.querySelector('#chatRoot .chat-msg'));
          check(document.querySelector('#chatRoot .chat-msg').textContent.includes('Browser synthetic chat'),'real chat widget payload');
          check((await(await get('/api/chat/state')).json()).unread===0,'chat not acknowledged');
          await get('/logout'); check(!(await get('/tickets/101')).url.includes('/login'),'GET logged out');
          await post('/logout',{}); check((await get('/tickets/101')).url.includes('/login'),'POST did not log out');
          const login=new DOMParser().parseFromString(await(await get('/login')).text(),'text/html');
          const token=login.querySelector('[name=csrf_token]').value;
          const response=await fetch('/login',{method:'POST',credentials:'same-origin',body:new URLSearchParams({csrf_token:token,username:'admin',password:'SyntheticOnly!12345'})});
          check(response.ok,'real browser login'); check(!(await get('/users')).url.includes('/login'),'admin login absent');
          document.body.textContent='PASS phase0 browser';
          await fetch('/__phase0_result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ok:true,userAgent:navigator.userAgent})});
        }catch(e){document.body.textContent='FAIL '+e.message;await fetch('/__phase0_result',{method:'POST',body:JSON.stringify({ok:false,error:e.message})})}})();
        """
        for name,executable in browsers.items():
            with self.subTest(browser=name):
                self.assertTrue(executable.is_file(),'Required browser unavailable: '+str(executable))
                self.execute('UPDATE users SET auth_version=0 WHERE id IN (1,8)')
                self.execute('DELETE FROM notifications'); self.execute("INSERT INTO notifications(user_id,title) VALUES(8,'Browser synthetic unread')")
                self.execute("DELETE FROM chat_messages WHERE to_id=8"); self.execute("INSERT INTO chat_messages(from_id,to_id,body) VALUES(2,8,'Browser synthetic chat')")
                result={}
                signed=self.m.app.session_interface.get_signing_serializer(self.m.app).dumps(dict(uid=8,role='Requester',name='Synthetic',csrf='browser-csrf',auth_version=0,issued_at=time.time(),_permanent=True))
                def application(environ,start_response):
                    path=environ['PATH_INFO']
                    if path=='/__phase0_browser':
                        response=Response('<html><head><meta name="csrf" content="browser-csrf"></head><body>WAIT<div id="chatRoot" data-me="8"></div><script src="/__phase0_driver.js"></script></body></html>',mimetype='text/html')
                        response.set_cookie('session',signed,secure=True,httponly=True,samesite='Lax')
                        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'"
                    elif path=='/__phase0_driver.js': response=Response(driver,mimetype='application/javascript')
                    elif path=='/__phase0_result':
                        result.update(json.loads(environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH') or 0))))
                        response=Response('ok')
                    else: return self.m.app(environ,start_response)
                    return response(environ,start_response)
                with tempfile.TemporaryDirectory(prefix='openitsm-browser-') as tmp,patch.dict(self.m.app.config,SESSION_COOKIE_SECURE=True):
                    cert,key=certificate(tmp); server,thread,port=tls_server(application,cert,key,4)
                    try:
                        command=[str(executable),'--headless=new','--disable-gpu','--no-first-run','--disable-sync','--disable-extensions','--disable-background-networking','--disable-component-update','--ignore-certificate-errors','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1','--user-data-dir='+str(Path(tmp)/'profile'),'--virtual-time-budget=12000','--dump-dom','https://127.0.0.1:'+str(port)+'/__phase0_browser']
                        kwargs={}
                        if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
                        completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=55,**kwargs)
                        self.assertEqual(completed.returncode,0,completed.stderr[-1500:])
                        self.assertIn('PASS phase0 browser',completed.stdout,completed.stdout[-2000:])
                        self.assertTrue(result.get('ok'),result)
                        self.runtime_evidence.append(dict(kind='browser',browser=name,**result))
                    finally: server.stop(); thread.join(timeout=5)
