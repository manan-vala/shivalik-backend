import os, re
for f in [
    'inventory/models/location.py',
    'inventory/models/stock.py',
    'inventory/models/vendor.py',
    'inventory/models/catalog.py',
    'inventory/migrations/0002_sprint0_full_schema.py'
]:
    with open(f, 'r') as file:
        content = file.read()
    content = re.sub(r'condition=', r'check=', content)
    with open(f, 'w') as file:
        file.write(content)
