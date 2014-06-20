# -*- mode: python; -*-

#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

# repository root directory
import os
import sys
sys.path.append('tools/build')

import rules
conf = Configure(DefaultEnvironment(ENV = os.environ))
env = rules.SetupBuildEnvironment(conf)

# Add a target to fetch third_party packages
env.Alias('fetch_packages', [
    env.Command('fetch_packages_thirdparty', [],
                'python third_party/fetch_packages.py'),
    env.Command('fetch_packages_distro_third_party', [],
        'bash -c "[ ! -f distro/third_party/fetch_packages.py ] || ' +
                    'python distro/third_party/fetch_packages.py"'),
])
env.Default('fetch_packages')

SConscript(dirs=['controller', 'vrouter', 'tools/sandesh'])

SConscript('openstack/nova_contrail_vif/SConscript',
           variant_dir='build/noarch/nova_contrail_vif')
