import os
import re

apps_path = os.path.join('apps')

excluded_files = ['__init__.py']

for root, dirs, files in os.walk(apps_path):
    if 'migrations' in dirs:
        for nroot, _, migration_files in os.walk(os.path.join(root, 'migrations')): # type: ignore
            for migration in migration_files:
                if migration not in excluded_files:
                    if os.path.exists(os.path.join(nroot, migration)) and os.path.isfile(os.path.join(nroot, migration)):
                        filename, file_extension = os.path.splitext(migration)
                        if (re.search(r'^[0-9]+_', migration) is not None and file_extension == '.py'): # or (file_extension == '.pyc'):
                            #print(migration)
                            os.remove(os.path.join(nroot, migration))
