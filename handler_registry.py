"""Pure, ordered registration with unchanged public endpoint names."""
import importlib

FAMILIES = ('read', 'tickets', 'infrastructure', 'identity', 'organization', 'collaboration')
CORE_ROUTES = (('/login', 'login', ('GET', 'POST')), ('/logout', 'logout', ('GET', 'POST')), ('/api/users/search', 'api_users_search', ('GET',)), ('/', 'dashboard', ('GET',)), ('/tickets', 'tickets', ('GET',)), ('/tickets/new', 'new_ticket', ('GET', 'POST')), ('/tickets/<int:tid>', 'ticket_detail', ('GET', 'POST')), ('/tasks', 'tasks_view', ('GET',)), ('/assets', 'assets', ('GET', 'POST')), ('/calendar', 'calendar', ('GET',)), ('/reports', 'reports', ('GET',)), ('/reports/export/<kind>/<fmt>', 'export_report', ('GET',)), ('/notifications', 'notifications', ('GET',)), ('/notifications/read', 'notifications_read', ('POST',)), ('/services', 'services', ('GET', 'POST')), ('/account', 'account', ('GET', 'POST')), ('/users', 'users_admin', ('GET', 'POST')), ('/admin', 'admin', ('GET', 'POST')), ('/admin/test-email', 'test_email', ('POST',)), ('/directory', 'directory', ('GET', 'POST')), ('/profile', 'profile', ('GET', 'POST')), ('/api/poll', 'api_poll', ('GET',)), ('/tasks/<int:taskid>', 'task_detail', ('GET',)), ('/tasks/<int:taskid>/complete', 'complete_task', ('POST',)), ('/tasks/<int:taskid>/do', 'task_do', ('POST',)), ('/audit', 'audit_view', ('GET',)), ('/audit/export/<fmt>', 'audit_export', ('GET',)))

def register_family(runtime, name):
    installed=getattr(runtime,'_handler_families',None)
    if installed is None:
        installed=[]
        runtime._handler_families=installed
    if name in installed:
        raise RuntimeError('Handler family already registered: '+name)
    if name not in FAMILIES or len(installed)>=len(FAMILIES) or FAMILIES[len(installed)]!=name:
        raise RuntimeError('Handler registration order mismatch')
    module=importlib.import_module('handlers.'+name)
    module.register(runtime)
    installed.append(name)

def register_core_routes(app, namespace):
    if app.extensions.get('openitsm_core_routes_registered'):
        raise RuntimeError('Core routes already registered')
    for path,endpoint,methods in CORE_ROUTES:
        if endpoint in app.view_functions or not callable(namespace.get(endpoint)):
            raise RuntimeError('Missing or duplicate endpoint: '+endpoint)
    for path,endpoint,methods in CORE_ROUTES:
        app.add_url_rule(path,endpoint=endpoint,view_func=namespace[endpoint],methods=methods)
    app.extensions['openitsm_core_routes_registered']=True
