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

if os.path.exists("openstack/contrail-nova-extensions/contrail_network_api/SConscript"):
    SConscript('openstack/contrail-nova-extensions/contrail_network_api/SConscript',
               variant_dir='build/noarch/contrail_nova_networkapi')

SConscript('openstack/neutron_plugin/SConscript',
           variant_dir='build/noarch/neutron_plugin')

if os.path.exists("openstack/ceilometer_plugin/SConscript"):
    SConscript('openstack/ceilometer_plugin/SConscript',
               variant_dir='build/noarch/ceilometer_plugin')

SConscript('contrail-f5/SConscript',
           variant_dir='build/noarch/contrail-f5')
