"""Legacy import/server entry point. Use application.create_app for isolated instances."""
import sys
from application import create_app

_application = create_app()
_runtime = _application.extensions['openitsm']['runtime']
if __name__ == '__main__':
    _runtime.run_server()
else:
    # Preserve legacy app.app/db/audit/... and existing helper patch semantics.
    sys.modules[__name__] = _runtime
