"""Explicit organization registration; existing scoped module owns its routes."""
import org

def register(runtime):
    runtime._org = org
    runtime._D = dict(db=runtime.db,login_required=runtime.login_required,current=runtime.current,
        audit=runtime.audit,notify=runtime.notify,now=runtime.now,setting=runtime.setting,
        GLOBAL=runtime.GLOBAL,AUDIT_ROLES=runtime.AUDIT_ROLES)
    runtime.ORG = org.init(runtime.app,runtime._D)
    runtime._D['org'] = runtime.ORG
