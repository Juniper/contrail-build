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

SConscript(dirs=['controller', 'vrouter', 'tools/sandesh'])

SConscript('openstack/nova_contrail_vif/SConscript',
           variant_dir='build/noarch/nova_contrail_vif')
