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

SConscript(dirs=['src/contrail-common', 'controller', 'vrouter'])

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

if os.path.exists("contrail-f5/SConscript"):
    SConscript('contrail-f5/SConscript',
               variant_dir='build/noarch/contrail-f5')

AddOption('--dump-targets', dest='dump_targets', action='store', type='string')
dump_targets = GetOption('dump_targets')
if dump_targets:
    rules.debug_targets_setup(env, dump_targets)
