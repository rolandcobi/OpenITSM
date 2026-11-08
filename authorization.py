"""Shared server-side directory read authorization policy.

Org-mode directory reads are scoped to the user's assigned unit subtree;
legacy mode preserves existing directory visibility until policy migration.
"""

def directory_scope_sql(user, org, connection, alias='u'):
    if dict(user).get('role') == 'System Administrator':
        return '1=1', []
    ids = org.scope_ids(connection,user) if org else []
    if not ids:
        return f'{alias}.id=?', [user['id']]
    return f'({alias}.id=? OR {alias}.org_unit_id IN ({",".join("?" for _ in ids)}))', [user['id'],*ids]

# Phase 0 default policy. Map legacy role names here; future configurable
# policies can replace this function without changing route handlers.
ROLE_CLASSES = {
    'System Administrator': 'administrator',
    'Central Administrator': 'administrator',
    'Service Desk Manager': 'manager',
    'Management': 'manager',
    'Local Administrator': 'manager',
    'Service Owner': 'manager',
    'Operational Operator': 'technician',
    'Requester': 'requester',
    'Auditor': 'auditor',
}


def asset_scope_sql(user, org, connection, alias='a'):
    """Assets use explicit unit assignments in both visibility modes.

    System Administrators are global; capabilities grant actions, not scope.
    Unassigned/ambiguous legacy assets are visible only to System Administrators.
    """
    if user['role'] == 'System Administrator':
        return '1=1', []
    if user['role'] not in ROLE_CLASSES or org is None:
        return '0=1', []
    ids = org.scope_ids(connection, user)
    if not ids:
        return '0=1', []
    ids = [r[0] for r in connection.execute(
        'SELECT id FROM org_units WHERE id IN (' + ','.join('?' for _ in ids) + ')', ids)]
    if not ids:
        return '0=1', []
    return f'{alias}.unit_id IN ({",".join("?" for _ in ids)})', ids


def service_write_scope_sql(user, org, connection, alias='s'):
    """Capabilities/ownership never bypass explicit unit scope on service writes.

    Shared (NULL-unit) services are managed only by System Administrators.
    Reads retain the shared catalog policy until that policy is reviewed.
    """
    return asset_scope_sql(user, org, connection, alias)

def ticket_scope_sql(user, org=None, connection=None, alias='t'):
    """Return a parameterized SQL predicate for all ticket list/export views.

    No cross-organization grant based on a free-text structure name.
    """
    role = ROLE_CLASSES.get(user['role'])
    if role is None:
        return '0=1', []
    uid = user['id']
    if user['role'] == 'System Administrator':
        return '1=1', []
    if role == 'requester':
        return f'{alias}.requester_id=?', [uid]
    if role == 'auditor':
        return '0=1', []
    if role == 'technician':
        return (f'({alias}.assignee_id=? OR EXISTS(SELECT 1 FROM tasks ta JOIN task_assignees x ON x.task_id=ta.id WHERE ta.ticket_id={alias}.id AND x.user_id=?) OR EXISTS(SELECT 1 FROM ticket_steps st WHERE st.ticket_id={alias}.id AND st.user_id=?))', [uid]*3)
    if org is not None:
        ids = org.scope_ids(connection, user)
        if not ids:
            return '0=1', []
        return f'{alias}.unit_id IN ({",".join("?" for _ in ids)})', list(ids)
    return '0=1', []


def directory_can_edit_target(actor, target, org, connection):
    """Fail closed on cross-unit edits; global admins may edit all units."""
    if actor['role'] not in ('System Administrator', 'Central Administrator'):
        return False
    if target['role'] == 'System Administrator' and actor['role'] != 'System Administrator':
        return False
    if actor['role'] == 'System Administrator':
        return True
    ids = org.scope_ids(connection, actor) if org else []
    target_fields=dict(target)
    if target_fields.get('org_head') and not dict(actor).get('org_head'):
        return False
    if ids and target_fields.get('org_head') and not set(org.scope_ids(connection,target)).issubset(ids):
        return False
    if ids and 'id' in target_fields:
        marks=','.join('?' for _ in ids)
        outside=connection.execute('''SELECT 1 FROM tickets t WHERE
            (t.assignee_id=? OR EXISTS(SELECT 1 FROM tasks ta JOIN task_assignees x ON x.task_id=ta.id WHERE ta.ticket_id=t.id AND x.user_id=?)
             OR EXISTS(SELECT 1 FROM ticket_steps st WHERE st.ticket_id=t.id AND st.user_id=?))
            AND (t.unit_id IS NULL OR t.unit_id NOT IN ('''+marks+')) LIMIT 1', [target['id']]*3+list(ids)).fetchone()
        if outside: return False
        outside_team=connection.execute('''SELECT 1 FROM team_members m
            JOIN teams team ON team.id=m.team_id JOIN users owner ON owner.id=team.owner_id
            WHERE m.user_id=? AND (owner.org_unit_id IS NULL OR owner.org_unit_id NOT IN ('''+marks+')) LIMIT 1', [target['id'],*ids]).fetchone()
        if outside_team: return False
    return bool(ids and target['org_unit_id'] in ids)


STAFF_ROLES = ('System Administrator','Central Administrator','Service Owner',
               'Service Desk Manager','Operational Operator','Local Administrator')


def can_delegate_user(actor, target, ticket_unit, org, connection):
    if not target or not target['active'] or target['role'] not in STAFF_ROLES:
        return False
    if actor['role']=='System Administrator':
        return True
    if actor['role'] not in STAFF_ROLES or not org:
        return False
    ids=org.scope_ids(connection,actor)
    return ticket_unit in ids and target['org_unit_id'] in ids


def service_read_scope_sql(user,org,connection,alias='s'):
    scope,args=asset_scope_sql(user,org,connection,alias)
    if user['role']=='System Administrator': return scope,args
    parent_scope,parent_args=asset_scope_sql(user,org,connection,'parent_s')
    return (f'({alias}.unit_id IS NULL OR {scope}) AND ({alias}.parent_service_id IS NULL OR EXISTS(SELECT 1 FROM services parent_s WHERE parent_s.id={alias}.parent_service_id AND (parent_s.unit_id IS NULL OR {parent_scope})))', [*args,*parent_args])
