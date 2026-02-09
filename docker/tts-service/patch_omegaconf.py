#!/usr/bin/env python3
"""
Patch omegaconf 2.0.6 wheel to fix broken metadata.
The PyYAML requirement has an invalid specifier (>=5.1.*)
"""
import urllib.request
import zipfile
import os

# Download omegaconf wheel
url = 'https://files.pythonhosted.org/packages/d0/eb/9d63ce09dd8aa85767c65668d5414958ea29648a0eec80a4a7d311ec2684/omegaconf-2.0.6-py3-none-any.whl'
urllib.request.urlretrieve(url, '/tmp/omegaconf.whl')

# Extract
with zipfile.ZipFile('/tmp/omegaconf.whl', 'r') as z:
    z.extractall('/tmp/omegaconf_fix')

# Read and fix METADATA
meta_path = '/tmp/omegaconf_fix/omegaconf-2.0.6.dist-info/METADATA'
with open(meta_path, 'r') as f:
    content = f.read()

# Fix the invalid specifier
fixed = content.replace('>=5.1.*', '>=5.1.0')
with open(meta_path, 'w') as f:
    f.write(fixed)

# Repack the wheel
os.chdir('/tmp/omegaconf_fix')
with zipfile.ZipFile('/tmp/omegaconf-2.0.6-py3-none-any.whl', 'w') as z:
    for root, dirs, files in os.walk('.'):
        for f in files:
            path = os.path.join(root, f)
            arcname = path[2:] if path.startswith('./') else path
            z.write(path, arcname)

print('Successfully patched omegaconf wheel')


