"""Per-application SQLite lifecycle and per-request transaction boundary."""
import contextvars
import sqlite3
import threading
from dataclasses import dataclass, field
from flask import current_app, has_request_context, request, session, Response

AUDIT_INSERT = 'INSERT INTO audit(actor_id,action,object_type,object_id,old_value,new_value,ip,created_at) VALUES(?,?,?,?,?,?,?,?)'
SECURITY_ACTIONS = frozenset(('AccessDenied','LoginFailed','PasswordChangeFailed'))

@dataclass
class RequestState:
    proxy: object = None
    callbacks: list = field(default_factory=list)
    audits: list = field(default_factory=list)
    finished: bool = False

class RequestConnection:
    """Legacy commits/closes defer to the owning request boundary."""
    def __init__(self, connection, state=None):
        self.raw = connection
        self.state = state if state is not None else RequestState()
    def __getattr__(self, name):
        return getattr(self.raw,name)
    def commit(self):
        pass
    def close(self):
        pass
    def rollback(self):
        try:
            self.raw.rollback()
        finally:
            self.state.callbacks.clear()
            self.state.audits.clear()

class Database:
    def __init__(self, app, path, commit):
        self.app = app
        self.path = path
        self.commit = commit
        self.initializing = True
        self.startup_connections = []

    def _state(self, create=False):
        if not has_request_context():
            return None
        if current_app._get_current_object() is not self.app:
            raise RuntimeError('Database used from another application request')
        owner = request._get_current_object()
        states = getattr(owner,'_openitsm_database_states',None)
        if states is None:
            if not create:
                return None
            states = {}
            owner._openitsm_database_states = states
        if create and self not in states:
            states[self] = RequestState()
        return states.get(self)

    def _open(self):
        connection = sqlite3.connect(self.path(),timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
            return connection
        except BaseException:
            connection.close()
            raise

    def connection(self):
        # Construction can occur under a caller's context; schema work always
        # uses this instance's raw connection, never a foreign request proxy.
        if self.initializing:
            connection = self._open()
            self.startup_connections.append(connection)
            return connection
        state = self._state(create=True)
        if state is None:
            return self._open()
        if state.finished:
            raise RuntimeError('Request transaction already finished')
        if state.proxy is None:
            state.proxy = RequestConnection(self._open(),state)
        return state.proxy

    def finish_initialization(self):
        self.initializing = False
        try:
            for connection in self.startup_connections:
                connection.close()
        finally:
            self.startup_connections.clear()

    def stage_audit(self, values):
        state = self._state(create=True)
        if state is not None:
            if state.finished:
                raise RuntimeError('Request transaction already finished')
            state.audits.append(values)

    def rollback(self):
        state = self._state()
        if state is not None and state.proxy is not None:
            state.proxy.rollback()
        elif state is not None:
            state.callbacks.clear()
            state.audits.clear()

    def after_commit(self, callback):
        state = self._state(create=True)
        if state is None:
            callback()
        elif state.finished:
            raise RuntimeError('Request transaction already finished')
        else:
            state.callbacks.append(callback)

    def dispatch_after_commit(self, function, *args, **kwargs):
        def dispatch():
            threading.Thread(target=lambda:contextvars.Context().run(function,*args,**kwargs),daemon=True).start()
        self.after_commit(dispatch)

    def finish(self, response):
        state = self._state()
        if state is None or state.finished:
            return response
        state.finished = True
        callbacks = list(state.callbacks)
        state.callbacks.clear()
        raw = state.proxy.raw if state.proxy is not None else None
        try:
            if raw is not None:
                if response.status_code >= 400:
                    raw.rollback()
                    security = [event for event in state.audits if event[1] in SECURITY_ACTIONS]
                    if security:
                        raw.executemany(AUDIT_INSERT,security)
                        self.commit(raw)
                elif raw.in_transaction:
                    self.commit(raw)
        except sqlite3.Error:
            try:
                if raw is not None:
                    raw.rollback()
            except sqlite3.Error:
                self.app.logger.error('Database rollback failed; connection will be closed')
            state.audits.clear()
            session.clear()
            self.app.logger.error('Database transaction failed; request changes were rolled back')
            return Response('Storage unavailable; no request changes were committed.',status=503)
        state.audits.clear()
        if response.status_code < 400:
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    self.app.logger.error('Deferred notification dispatch failed')
        return response

    def close_request(self, error=None):
        state = self._state()
        if state is None:
            return
        try:
            if state.proxy is not None:
                raw = state.proxy.raw
                try:
                    if raw.in_transaction:
                        raw.rollback()
                finally:
                    raw.close()
        except sqlite3.Error:
            self.app.logger.error('Database teardown failed')
        finally:
            state.callbacks.clear()
            state.audits.clear()
            request._get_current_object()._openitsm_database_states.pop(self,None)
