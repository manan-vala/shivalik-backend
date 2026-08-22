import os, re
for f in [
    'inventory/models/location.py',
    'inventory/models/stock.py',
    'inventory/models/vendor.py',
    'inventory/models/catalog.py'
]:
    with open(f, 'r') as file:
        content = file.read()
    content = re.sub(r'(models\.CheckConstraint\([^)]*)condition=', r'\1check=', content)
    with open(f, 'w') as file:
        file.write(content)
