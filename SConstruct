# -*- mode: python; -*-

#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

# repository root directory
import os
import sys
sys.path.append('tools/build')

import rules
env = DefaultEnvironment(ENV = os.environ)
rules.SetupBuildEnvironment(env)

SConscript(dirs=['controller', 'vrouter', 'tools/sandesh'])
