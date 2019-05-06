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

if sys.platform.startswith('win'):
    SConscript(dirs=['windows', 'src/contrail-common', 'controller', 'vrouter'])
else:
    SConscript(dirs=['src/contrail-common', 'controller', 'vrouter'])



if os.path.exists('openstack/nova_contrail_vif/SConscript'):
    SConscript('openstack/nova_contrail_vif/SConscript',
               variant_dir='build/noarch/nova_contrail_vif')

if os.path.exists("openstack/contrail-nova-extensions/contrail_network_api/SConscript"):
    SConscript('openstack/contrail-nova-extensions/contrail_network_api/SConscript',
               variant_dir='build/noarch/contrail_nova_networkapi')

if os.path.exists('openstack/neutron_plugin/SConscript'):
    SConscript('openstack/neutron_plugin/SConscript',
               variant_dir='build/noarch/neutron_plugin')

if os.path.exists("openstack/ceilometer_plugin/SConscript"):
    SConscript('openstack/ceilometer_plugin/SConscript',
               variant_dir='build/noarch/ceilometer_plugin')

if os.path.exists("contrail-f5/SConscript"):
    SConscript('contrail-f5/SConscript',
               variant_dir='build/noarch/contrail-f5')

if os.path.exists("vcenter-manager/SConscript"):
    SConscript('vcenter-manager/SConscript',
               variant_dir='build/noarch/vcenter-manager')

if os.path.exists("vcenter-fabric-manager/SConscript"):
    SConscript('vcenter-fabric-manager/SConscript',
               variant_dir='build/noarch/vcenter-fabric-manager')

if GetOption("describe-tests"):
    rules.DescribeTests(env, COMMAND_LINE_TARGETS)
    Exit(0)

if GetOption("describe-aliases"):
    rules.DescribeAliases()
    Exit(0)
