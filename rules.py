#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

import json
import os
import re
from SCons.Builder import Builder
from SCons.Action import Action
from SCons.Errors import convert_to_BuildError
from SCons.Script import AddOption, GetOption, SetOption
from distutils.version import LooseVersion, StrictVersion
import json
import SCons.Util
import subprocess
import sys
import time
import platform
import getpass
import warnings

def GetPlatformInfo(env):
    '''
    Returns same 3-tuple as platform.dist()/platform.linux_distribution() (caches tuple)
    '''
    GetPlatformInfo.__dict__.setdefault('system', None)
    GetPlatformInfo.__dict__.setdefault('distro', None)
    if not GetPlatformInfo.system: GetPlatformInfo.system = platform.system()

    if not GetPlatformInfo.distro:
        if GetPlatformInfo.system == 'Linux':
            GetPlatformInfo.distro = platform.linux_distribution()
        elif GetPlatformInfo.system == 'Darwin':
            GetPlatformInfo.distro = ('Darwin','','')
        else:
            GetPlatformInfo.distro = ('Unknown','','')

    return GetPlatformInfo.distro

def PlatformExclude(env, **kwargs):
    """
    Return True if platform_excludes list includes a tuple that matches this host/version
    """
    if 'platform_exclude' not in kwargs: return False

    from distutils.version import LooseVersion

    distro = env.GetPlatformInfo()
    this_ver = LooseVersion(distro[1])

    for (p,v) in kwargs['platform_exclude']:
        if distro[0] != p: continue
        excl_ver = LooseVersion(v)
        if this_ver >= excl_ver: return True
    return False

def GetTestEnvironment(test):
    env = { }
    try:
        with open('controller/ci_unittests.json') as json_file:
            d = json.load(json_file)
            for e in d["contrail-control"]["environment"]:
                for t in e["tests"]:
                    if re.compile(t).match(test):
                        for tup in e["tuples"]:
                            tokens = tup.split("=")
                            env[tokens[0]] = tokens[1]
    except:
        pass
    return env

def RunUnitTest(env, target, source, timeout = 300):
    if 'BUILD_ONLY' in env['ENV']:
        return
    import subprocess

    if 'CONTRAIL_UT_TEST_TIMEOUT' in env['ENV']:
        timeout = int(env['ENV']['CONTRAIL_UT_TEST_TIMEOUT'])

    test = str(source[0].abspath)
    logfile = open(target[0].abspath, 'w')
    #    env['_venv'] = {target: venv}
    tgt = target[0].name
    if '_venv' in  env and tgt in env['_venv'] and env['_venv'][tgt]:
        cmd = ['/bin/bash', '-c', 'source %s/bin/activate && %s' % (
                env[env['_venv'][tgt]]._path, test)]
    elif env.get('OPT') == 'valgrind':
        cmd = ['valgrind', '--track-origins=yes', '--num-callers=50',
               '--show-possibly-lost=no', '--leak-check=full',
               '--error-limit=no', test]
    else:
        cmd = [test]

    ShEnv = env['ENV'].copy()
    ShEnv.update({env['ENV_SHLIB_PATH']: 'build/lib',
                  'DB_ITERATION_TO_YIELD': '1',
                  'TOP_OBJECT_PATH': env['TOP'][1:]})

    ShEnv.update(GetTestEnvironment(test))
    # Use gprof unless NO_HEAPCHECK is set or in CentOS or in Windows
    heap_check = 'NO_HEAPCHECK' not in ShEnv
    if heap_check:
        if platform.system() == 'Windows':
            heap_check = False
        else:
            try:
                # Skip HEAPCHECK in CentOS 6.4
                subprocess.check_call("grep -q \"CentOS release 6.4\" /etc/issue 2>/dev/null", shell=True)
                heap_check = False
            except:
                pass

    if heap_check:
        ShEnv['HEAPCHECK'] = 'normal'
        ShEnv['PPROF_PATH'] = 'build/bin/pprof'
        # Fix for frequent crash in gperftools ListerThread during exit
        # https://code.google.com/p/gperftools/issues/detail?id=497
        ShEnv['LD_BIND_NOW'] = '1'

    if 'CONCURRENCY_CHECK_ENABLE' not in ShEnv:
        ShEnv['CONCURRENCY_CHECK_ENABLE'] = 'true'
    proc = subprocess.Popen(cmd, stdout=logfile, stderr=logfile, env=ShEnv)

    # 60 second timeout
    for i in range(timeout):
        code = proc.poll()
        if not code is None:
            break
        time.sleep(1)

    if code is None:
        proc.kill()
        logfile.write('[  TIMEOUT  ] ')
        print(test + '\033[91m' + " TIMEOUT" + '\033[0m')
        raise convert_to_BuildError(code)
        return

    if code == 0:
        print(test + '\033[94m' + " PASS" + '\033[0m')
    else:
        logfile.write('[  FAILED  ] ')
        if code < 0:
            logfile.write('Terminated by signal: ' + str(-code) + '\n')
        else:
            logfile.write('Program returned ' + str(code) + '\n')
        print(test + '\033[91m' + " FAIL" + '\033[0m')
        raise convert_to_BuildError(code)

def TestSuite(env, target, source):
    if len(source):
        for test in env.Flatten(source):
            # UnitTest() may have tagged tests with skip_run attribute
            if getattr( test.attributes, 'skip_run', False ): continue

            xml_path = test.abspath + '.xml'
            log_path = test.abspath + '.log'
            env.tests.add_test(node_path=log_path, xml_path=xml_path, log_path=log_path)

            # GTest framework uses environment variables to configure how to write
            # the test output, with GTEST_OUTPUT variable. Make sure targets
            # don't share their environments, so that GTEST_OUTPUT is not
            # overwritten.
            isolated_env = env['ENV'].copy()
            isolated_env['GTEST_OUTPUT'] = 'xml:' + xml_path
            cmd = env.Command(log_path, test, RunUnitTest, ENV=isolated_env)

            # If BUILD_ONLY set, do not alias foo.log target, to avoid
            # invoking the RunUnitTest() as a no-op (i.e., this avoids
            # some log clutter)
            if 'BUILD_ONLY' in env['ENV']:
                env.Alias(target, test)
            else:
                env.AlwaysBuild(cmd)
                env.Alias(target, cmd)
        return target

def GetVncAPIPkg(env):
    h,v = env.GetBuildVersion()
    return '/api-lib/dist/contrail-api-client-%s.tar.gz' % v

sdist_default_depends = [
    '/config/common/dist/cfgm_common-0.1dev.tar.gz',
    '/tools/sandesh/library/python/dist/sandesh-0.1dev.tar.gz',
    '/sandesh/common/dist/sandesh-common-0.1dev.tar.gz',
]

# SetupPyTestSuiteWithDeps
#
# Function to provide consistent 'python setup.py run_tests' interface
#
# The var *args is expected to contain a list of dependencies. If
# *args is empty, then above sdist_default_depends + the vnc_api tgz
# is used.
#
# This method is mostly to be used by SetupPyTestSuite(), but there
# is one special-case instance (controller/src/api-lib) that needs
# to use this builder directly, so that it can provide explicit list
# of dependencies.
#
def SetupPyTestSuiteWithDeps(env, sdist_target, *args, **kwargs):
    use_tox = kwargs['use_tox'] if 'use_tox' in kwargs else False

    buildspace_link = os.environ.get('CONTRAIL_REPO')
    if buildspace_link:
        # in CI environment shebang limit exceeds for python
        # in easy_install/pip, reach to it via symlink
        top_dir = env.Dir(buildspace_link + '/' + env.Dir('.').path)
    else:
        top_dir = env.Dir('.')

    cmd_base = 'bash -c "set -o pipefail && cd ' + env.Dir(top_dir).path + ' && %s 2>&1 | tee %s.log"'

    # if BUILD_ONLY, we create a "pass through" dependency... the test target will end up depending
    # (only) on the original sdist target
    if 'BUILD_ONLY' in env['ENV']:
        test_cmd = cov_cmd = sdist_target
    else:
        cmd_str = 'tox' if use_tox else 'python setup.py run_tests'
        test_cmd = env.Command('test.log', sdist_target, cmd_base % (cmd_str, "test"))
        cmd_str += ' -e cover' if use_tox else ' --coverage'
        cov_cmd = env.Command('coveragetest.log', sdist_target, cmd_base % (cmd_str, 'coveragetest'))

    # If *args is not empty, move all arguments to kwargs['sdist_depends']
    # and issue a warning. Also make sure we are not using old and new method
    # of passing dependencies.
    if len(args) and 'sdist_depends' in kwargs:
        print("Do not both pass dependencies as *args"
              "and use sdist_depends at the same time.")
        Exit(1)

    # during transition we have to support both types of targets
    # as dependencies. This function allows us to mix both SCons targets
    # and file paths.
    def _rewrite_file_dependencies(deps):
        """Update direct file dependencies to prepend build path"""
        # file dependencies need absulute paths
        file_depends = [env['TOP'] + x for x in deps if x.startswith('/')]
        # explicitly define each target as Alias, in case it hasn't yet been
        # defined in SConscript.
        scons_depends = [env.Alias(x) for x in deps if not x.startswith('/')]
        return file_depends + scons_depends

    if len(args):
        warnings.warn("Don't pass dependencies as arguments pointing"
                      " to tarballs, instead pass scons aliases"
                      " as sdist_depends.")
        full_depends = _rewrite_file_dependencies(env.Flatten(args))
    else:
        full_depends = _rewrite_file_dependencies(kwargs['sdist_depends'])

    # When BUILD_ONLY is defined, test_cmd and cov_cmd are replaced with
    # sdist_target - that can lead to circular dependencies when tests
    # depend on other components.
    if 'BUILD_ONLY' not in env['ENV']:
        env.Depends(test_cmd, full_depends)
        env.Depends(cov_cmd, full_depends)

    d = env.Dir('.').srcnode().path
    env.Alias( d + ':test', test_cmd )
    env.Alias( d + ':coverage', cov_cmd )
    # env.Depends('test', test_cmd) # XXX This may need to be restored
    env.Depends('coverage', cov_cmd)

    xml_path = env.Dir(".").abspath + "/test-results.xml"
    log_path = env.Dir(".").abspath + "/test.log"
    env.tests.add_test(node_path=log_path, xml_path=xml_path, log_path=log_path)

# SetupPyTestSuite()
#
# General entry point for setting up 'python setup.py run_tests'. If
# using this method, the default dependencies are assumed. Any
# additional arguments in *args are *additional* dependencies
#
def SetupPyTestSuite(env, sdist_target, *args, **kwargs):
    sdist_depends = sdist_default_depends + [ env.GetVncAPIPkg() ]
    if len(args): sdist_depends += args

    env.SetupPyTestSuiteWithDeps(sdist_target,
                                 sdist_depends=sdist_depends, **kwargs)

def setup_venv(env, target, venv_name, path=None):
    p = path
    if not p:
        ws_link = os.environ.get('CONTRAIL_REPO')
        if ws_link: p = ws_link + "/build/" + env['OPT']
        else: p = env.Dir(env['TOP']).abspath

    tdir = '/tmp/cache/%s/systemless_test' % getpass.getuser()
    shell_cmd = ' && '.join ([
        'cd %s' % p,
        'mkdir -p %s' % tdir,
        '[ -f %s/ez_setup-0.9.tar.gz ] || curl -o %s/ez_setup-0.9.tar.gz https://pypi.python.org/packages/source/e/ez_setup/ez_setup-0.9.tar.gz' % (tdir,tdir),
        '[ -d ez_setup-0.9 ] || tar xzf %s/ez_setup-0.9.tar.gz' % tdir,
        '[ -f %s/redis-2.6.13.tar.gz ] || (cd %s && wget https://storage.googleapis.com/google-code-archive-downloads/v2/code.google.com/redis/redis-2.6.13.tar.gz)' % (tdir,tdir),
        '[ -d ../redis-2.6.13 ] || (cd .. && tar xzf %s/redis-2.6.13.tar.gz)' % tdir,
        '[ -f testroot/bin/redis-server ] || ( cd ../redis-2.6.13 && make PREFIX=%s/testroot install)' % p,
        'virtualenv %s',
    ])
    for t, v in zip(target, venv_name):
        cmd = env.Command (v, '', shell_cmd % (v,))
        env.Alias (t, cmd)
        cmd._path = '/'.join ([p, v])
        env[t] = cmd
    return target

def venv_add_pip_pkg(env, v, pkg_list):
    venv = env[v[0]]

    # pkg_list can contain absolute filenames or a pip package and version.
    targets = []
    for pkg in pkg_list:
        result = pkg.split('==')
        if result:
            name = result[0]
        else:
            name = pkg
        if name[0] != '/':
            targets.append(name)

    pip = "/bin/bash -c \"source %s/bin/activate 2>/dev/null; pip" % venv._path
    download_cache = ""
    if sys.platform != 'win32':
        pip_version = subprocess.check_output(
            "%s --version | awk '{print \$2}'\"" % pip, shell=True).rstrip()
        if pip_version < LooseVersion("6.0"):
            tdir = '/tmp/cache/%s/systemless_test' % getpass.getuser()
            download_cache = "--download-cache=%s" % (tdir)

    cmd = env.Command(targets, None, '%s install %s %s"' %
                                     (pip, download_cache, ' '.join(pkg_list)))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def venv_add_build_pkg(env, v, pkg):
    cmd = []
    venv = env[v[0]]
    for p in pkg:
        t = 'build-' + p.replace('/', '_')
        cmd += env.Command (t, '',
       '/bin/bash -c "source %s/bin/activate; pushd %s && python setup.py install; popd"' % (
              venv._path, p))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def PyTestSuite(env, target, source, venv=None):
    if 'BUILD_ONLY' in env['ENV']:
        return target
    for test in source:
        log = test + '.log'
        if venv:
            try:
                env['_venv'][log] = venv[0]
            except KeyError:
                env['_venv'] = {log: venv[0]}
        cmd = env.Command(log, test, RunUnitTest)
        if venv:
            env.Depends(cmd, venv)
        env.AlwaysBuild(cmd)
        env.Alias(target, cmd)
    return target

def UnitTest(env, name, sources, **kwargs):
    test_env = env.Clone()

    # Do not link with tcmalloc when running under valgrind/coverage env.
    if sys.platform not in ['darwin', 'win32'] and env.get('OPT') != 'coverage' and \
           not env['ENV'].has_key('NO_HEAPCHECK') and env.get('OPT') != 'valgrind':
        test_env.Append(LIBPATH = '#/build/lib')
        test_env.Append(LIBS = ['tcmalloc'])
    test_exe_list = test_env.Program(name, sources)
    if test_env.PlatformExclude(**kwargs):
        for t in test_exe_list: t.attributes.skip_run = True
    return test_exe_list

# Returns True if the build is being done by a CI job,
# by Jenkins, or some other official or automated build
def IsAutomatedBuild():
    return 'ZUUL_CHANGES' in os.environ or 'BUILD_BRANCH' in os.environ

# Return True if we want quiet/short CLI echo for gcc/g++/gld/etc
# Default is same as IsAutomatedBuild(), but we return
# false if BUILD_QUIET is set to something that looks like "true"
def WantQuietOutput():
    v = os.environ.get('BUILD_QUIET', IsAutomatedBuild())
    return v in [ True, "True", "TRUE", "true", "yes", "1" ]

# we are not interested in source files for the dependency, but rather
# to force rebuilds. Pass an empty source to the env.Command, to break
# circular dependencies.
# XXX: This should be rewritten using SCons Value nodes (for generating
# build info itself) and Builder for managing targets.
def GenerateBuildInfoCode(env, target, source, path):
    o = env.Command(target=target, source=[], action=BuildInfoAction)

    # if we are running under CI or jenkins-driven CB/OB build,
    # we do NOT want to use AlwaysBuild, as it triggers unnecessary
    # rebuilds.
    if not IsAutomatedBuild(): env.AlwaysBuild(o)

    return

# If contrail-controller (i.e., #controller/) is present, determine
# git hash of head and get base version from version.info, else use
# hard-coded values.
#
def GetBuildVersion(env):
    # Fetch git version
    controller_path = env.Dir('#controller').path
    if os.path.exists(controller_path):
        p = subprocess.Popen('cd %s && git rev-parse --short HEAD' % controller_path,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             shell='True')
        git_hash, err = p.communicate()
        git_hash = git_hash.strip()
    else:
        # Or should we look for vrouter, tools/build, or ??
        git_hash = 'noctrlr'

    # Fetch build version
    file_path = env.File('#/controller/src/base/version.info').abspath
    if os.path.exists(file_path):
        f = open(file_path)
        base_ver = (f.readline()).strip()
    else:
        base_ver = "3.0"

    return git_hash, base_ver

def GetBuildInfoData(env, target, source):
    try:
        build_user = os.environ['USER']
    except KeyError:
        build_user = "unknown"

    try:
        build_host = env['HOSTNAME']
    except KeyError:
        build_host = "unknown"

    # Fetch Time in UTC
    import datetime
    build_time = str(datetime.datetime.utcnow())

    build_git_info, build_version = GetBuildVersion(env)

    # build json string containing build information
    info = {
        'build-version': build_version,
        'build-time': build_time,
        'build-user': build_user,
        'build-hostname': build_host
    }

    return json.dumps({'build-info': [info]})


def BuildInfoAction(env, target, source):
    build_dir = target[0].dir.path
    jsdata = GetBuildInfoData(env, target, source)

    h_code = """
/*
 * Autogenerated file. DO NOT EDIT
 */
#ifndef ctrlplane_buildinfo_h
#define ctrlplane_buildinfo_h
#include <string>
extern const std::string BuildInfo;
#endif // ctrlplane_buildinfo_h"

"""

    cc_code = """
/*
 * Autogenerated file. DO NOT EDIT.
 */
#include "buildinfo.h"

const std::string BuildInfo = "%(json)s";
""" % { 'json': jsdata.replace('"', "\\\"") }

    with open(os.path.join(build_dir, 'buildinfo.h'), 'w') as h_file:
        h_file.write(h_code)

    with open(os.path.join(build_dir, 'buildinfo.cc'), 'w') as cc_file:
        cc_file.write(cc_code)
#end BuildInfoAction

def GenerateBuildInfoCCode(env, target, source, path):
    build_dir = path
    jsdata = GetBuildInfoData(env, target, source)

    c_code = """
/*
 * Autogenerated file. DO NOT EDIT.
 */

const char *ContrailBuildInfo = "%(json)s";
""" % { 'json': jsdata.replace('"', "\\\"") }

    with open(os.path.join(build_dir, target[0]), 'w') as c_file:
        c_file.write(c_code)
#end GenerateBuildInfoCCode

def GenerateBuildInfoPyCode(env, target, source, path):
    import os
    import subprocess

    try:
        build_user = getpass.getuser()
    except KeyError:
        build_user = "unknown"

    try:
        build_host = env['HOSTNAME']
    except KeyError:
        build_host = "unknown"

    # Fetch Time in UTC
    import datetime
    build_time = datetime.datetime.utcnow()

    build_git_info, build_version = GetBuildVersion(env)

    # build json string containing build information
    build_info = "{\\\"build-info\\\" : [{\\\"build-version\\\" : \\\"" + str(build_version) + "\\\", \\\"build-time\\\" : \\\"" + str(build_time) + "\\\", \\\"build-user\\\" : \\\"" + build_user + "\\\", \\\"build-hostname\\\" : \\\"" + build_host + "\\\", "
    py_code ="build_info = \""+ build_info + "\";\n"
    with open(path + '/buildinfo.py', 'w') as py_file:
        py_file.write(py_code)

    return target

#end GenerateBuildInfoPyCode

def Basename(path):
    return path.rsplit('.', 1)[0]

# ExtractCpp Method
def ExtractCppFunc(env, filelist):
    CppSrcs = []
    for target in filelist:
        fname = str(target)
        ext = fname.rsplit('.', 1)[1]
        if ext == 'cpp' or ext == 'cc':
            CppSrcs.append(fname)
    return CppSrcs

# ExtractC Method
def ExtractCFunc(env, filelist):
    CSrcs = []
    for target in filelist:
        fname = str(target)
        ext = fname.rsplit('.', 1)[1]
        if ext == 'c':
            CSrcs.append(fname)
    return CSrcs

# ExtractHeader Method
def ExtractHeaderFunc(env, filelist):
    Headers = []
    for target in filelist:
        fname = str(target)
        ext = fname.rsplit('.', 1)[1]
        if ext == 'h':
            Headers.append(fname)
    return Headers

# ProtocDesc Methods
def ProtocDescBuilder(target, source, env):
    if not env.Detect('protoc'):
        raise SCons.Errors.StopError(
            'protoc Compiler not detected on system')
    etcd_incl = os.environ.get('CONTRAIL_ETCD_INCL')
    if etcd_incl:
        protoc = env.Dir('#/third_party/grpc/bins/opt/protobuf').abspath + '/protoc'
        protop = ' --proto_path=build/include/ '
    else:
        protoc = env.WhereIs('protoc')
        protop = ' --proto_path=/usr/include/ '
    protoc_cmd = protoc + ' --descriptor_set_out=' + \
        str(target[0]) + ' --include_imports ' + \
        ' --proto_path=controller/src/' + \
        protop + \
        ' --proto_path=src/contrail-analytics/contrail-collector/ ' + \
        str(source[0])
    print(protoc_cmd)
    code = subprocess.call(protoc_cmd, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(
            'protobuf desc generation failed')

def ProtocSconsEnvDescFunc(env):
    descbuild = Builder(action = ProtocDescBuilder)
    env.Append(BUILDERS = {'ProtocDesc' : descbuild})

def ProtocGenDescFunc(env, file):
    ProtocSconsEnvDescFunc(env)
    suffixes = ['.desc']
    basename = Basename(file)
    targets = map(lambda suffix: basename + suffix, suffixes)
    return env.ProtocDesc(targets, file)

# ProtocCpp Methods
def ProtocCppBuilder(target, source, env):
    spath = str(source[0]).rsplit('/',1)[0] + "/"
    if not env.Detect('protoc'):
        raise SCons.Errors.StopError(
            'protoc Compiler not detected on system')
    etcd_incl = os.environ.get('CONTRAIL_ETCD_INCL')
    if etcd_incl:
        protoc = env.Dir('#/third_party/grpc/bins/opt/protobuf').abspath + '/protoc'
        protop = ' --proto_path=build/include/ '
    else:
        protoc = env.WhereIs('protoc')
        protop = ' --proto_path=/usr/include/ '
    protoc_cmd = protoc + protop + \
        ' --proto_path=src/contrail-analytics/contrail-collector/ ' + \
        '--proto_path=controller/src/ --proto_path=' + \
        spath + ' --cpp_out=' + str(env.Dir(env['TOP'])) + \
        env['PROTOC_MAP_TGT_DIR'] + ' ' + \
        str(source[0])
    print(protoc_cmd)
    code = subprocess.call(protoc_cmd, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(
            'protobuf code generation failed')

def ProtocSconsEnvCppFunc(env):
    cppbuild = Builder(action = ProtocCppBuilder)
    env.Append(BUILDERS = {'ProtocCpp' : cppbuild})

def ProtocGenCppMapTgtDirFunc(env, file, target_root = ''):
    if target_root == '':
        env['PROTOC_MAP_TGT_DIR'] = ''
    else:
        env['PROTOC_MAP_TGT_DIR'] = '/' + target_root
    ProtocSconsEnvCppFunc(env)
    suffixes = ['.pb.h',
                '.pb.cc'
               ]
    basename = Basename(file)
    targets = map(lambda suffix: basename + suffix, suffixes)
    return env.ProtocCpp(targets, file)

def ProtocGenCppFunc(env, file):
    return (ProtocGenCppMapTgtDirFunc(env, file, ''))

# When doing parallel build, scons will sometimes try to invoke the
# sandesh compiler while sandesh itself is still being compiled and
# linked. This results in a 'text file busy' error, and the build
# aborts.
# To avoid this, a 'wait for it' loop... we run 'sandesh -version',
# and sleep for one sec before retry if it fails.
#
# This is a terrible hack, and should be fixed, but all attempts to
# get scons to recognize the dependency on the sandesh compailer have
# so far been fruitless.
#
def wait_for_sandesh_install(env):
    rc = 0
    while (rc != 1):
        with open(os.devnull, "w") as f:
            try:
                rc = subprocess.call([env['SANDESH'], '-version'], stdout=f, stderr=f)
            except Exception as e:
                rc = 0
        if (rc != 1):
            print('scons: warning: sandesh -version returned %d, retrying' % rc)
            time.sleep(1)

class SandeshWarning(SCons.Warnings.Warning):
    pass

class SandeshCodeGeneratorError(SandeshWarning):
    pass

# SandeshGenDoc Methods
def SandeshDocBuilder(target, source, env):
    opath = target[0].dir.path
    wait_for_sandesh_install(env)
    code = subprocess.call(env['SANDESH'] + ' --gen doc -I controller/src/ -I src/contrail-common -out '
                           + opath + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshDoc documentation generation failed')

def SandeshSconsEnvDocFunc(env):
    docbuild = Builder(action = Action(SandeshDocBuilder, 'SandeshDocBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshDoc' : docbuild})

def SandeshGenDocFunc(env, filepath, target=''):
    SandeshSconsEnvDocFunc(env)
    suffixes = ['.html',
                '_index.html',
                '_logs.html',
                '_logs.doc.schema.json',
                '_logs.emerg.html',
                '_logs.emerg.doc.schema.json',
                '_logs.alert.html',
                '_logs.alert.doc.schema.json',
                '_logs.crit.html',
                '_logs.crit.doc.schema.json',
                '_logs.error.html',
                '_logs.error.doc.schema.json',
                '_logs.warn.html',
                '_logs.warn.doc.schema.json',
                '_logs.notice.html',
                '_logs.notice.doc.schema.json',
                '_logs.info.html',
                '_logs.info.doc.schema.json',
                '_logs.debug.html',
                '_logs.debug.doc.schema.json',
                '_logs.invalid.html',
                '_logs.invalid.doc.schema.json',
                '_uves.html',
                '_uves.doc.schema.json',
                '_traces.html',
                '_traces.doc.schema.json',
                '_introspect.html',
                '_introspect.doc.schema.json',
                '_stats_tables.json']
    basename = Basename(filepath)
    path_split = basename.rsplit('/', 1)
    if len(path_split) == 2:
        filename = path_split[1]
    else:
        filename = path_split[0]
    targets = [target + 'gen-doc/' + filename + suffix for suffix in suffixes]
    env.Depends(targets, '#build/bin/sandesh' + env['PROGSUFFIX'])
    return env.SandeshDoc(targets, filepath)

# SandeshGenOnlyCpp Methods
def SandeshOnlyCppBuilder(target, source, env):
    sname = os.path.splitext(source[0].name)[0] # file name w/o .sandesh
    html_cpp_name = os.path.join(target[0].dir.path, sname + '_html.cpp')

    wait_for_sandesh_install(env)
    code = subprocess.call(env['SANDESH'] + ' --gen cpp -I controller/src/ -I src/contrail-common -out ' +
                           target[0].dir.path + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshOnlyCpp code generation failed')
    with open(html_cpp_name, 'a') as html_cpp_file:
        html_cpp_file.write('int ' + sname + '_marker = 0;\n')

def SandeshSconsEnvOnlyCppFunc(env):
    onlycppbuild = Builder(action = Action(SandeshOnlyCppBuilder,'SandeshOnlyCppBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshOnlyCpp' : onlycppbuild})

def SandeshGenOnlyCppFunc(env, file, extra_suffixes=[]):
    SandeshSconsEnvOnlyCppFunc(env)
    suffixes = ['_types.h',
        '_types.cpp',
        '_constants.h',
        '_constants.cpp',
        '_html.cpp']

    if extra_suffixes:
        if isinstance(extra_suffixes, basestring):
            extra_suffixes = [ extra_suffixes ]
        suffixes += extra_suffixes

    basename = Basename(file)
    targets = [basename + suffix for suffix in suffixes]
    env.Depends(targets, '#build/bin/sandesh' + env['PROGSUFFIX'])
    return env.SandeshOnlyCpp(targets, file)

# SandeshGenCpp Methods
def SandeshCppBuilder(target, source, env):
    opath = target[0].dir.path
    sname = os.path.join(opath, os.path.splitext(source[0].name)[0])

    wait_for_sandesh_install(env)
    code = subprocess.call(env['SANDESH'] + ' --gen cpp --gen html -I controller/src/ -I src/contrail-common -out '
                           + opath + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshCpp code generation failed')
    tname = sname + "_html_template.cpp"
    hname = os.path.basename(sname + ".xml")
    cname = sname + "_html.cpp"
    if not env.Detect('xxd'):
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'xxd not detected on system')
    with open(cname, 'w') as cfile:
        cfile.write('namespace {\n')

    # If one passes file to `stdout` kwarg to subprocess.call on Windows, it gets fileno from this
    # file, then handle for that fileno and forwards stdout to that handle, which means it bypasses
    # Python's internal buffer and sometimes writes before our previous call to `write` method.
    # Besides, probably due to some bug in subprocess on Windows, it opens handles to other files in
    # that folder (checked with handle64 from Windows Sysinternals) so it sometimes breaks
    # multithreaded builds when it opens a handle to file used by another thread. For that reason we
    # can't use `stdout` kwarg here. If there's a need to get rid of shell redirection, one should
    # get rid of calling xxd at all - this feature should be done in native Python code.
    subprocess.call('xxd -i ' + hname + ' >> ' + os.path.basename(cname), shell=True, cwd=opath)
    with open(cname, 'a') as cfile:
        cfile.write('}\n')
        with open(tname, 'r') as tfile:
            for line in tfile:
                cfile.write(line)

def SandeshSconsEnvCppFunc(env):
    cppbuild = Builder(action = Action(SandeshCppBuilder, 'SandeshCppBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshCpp' : cppbuild})

def SandeshGenCppFunc(env, file, extra_suffixes=[]):
    SandeshSconsEnvCppFunc(env)
    suffixes = ['_types.h',
        '_types.cpp',
        '_constants.h',
        '_constants.cpp',
        '_html.cpp']

    if extra_suffixes:
        if isinstance(extra_suffixes, basestring):
            extra_suffixes = [ extra_suffixes ]
        suffixes += extra_suffixes

    basename = Basename(file)
    targets = [basename + suffix for suffix in suffixes]
    env.Depends(targets, '#build/bin/sandesh' + env['PROGSUFFIX'])
    return env.SandeshCpp(targets, file)

# SandeshGenC Methods
def SandeshCBuilder(target, source, env):
    # We need to trim the /gen-c/ out of the target path
    opath = os.path.dirname(target[0].dir.path)
    wait_for_sandesh_install(env)
    code = subprocess.call(env['SANDESH'] + ' --gen c -o ' + opath +
                           ' ' + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshC code generation failed')

def SandeshSconsEnvCFunc(env):
    cbuild = Builder(action = Action(SandeshCBuilder, 'SandeshCBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshC' : cbuild})

def SandeshGenCFunc(env, file):
    SandeshSconsEnvCFunc(env)
    suffixes = ['_types.h', '_types.c']
    basename = Basename(file)
    targets = ['gen-c/' + basename + suffix for suffix in suffixes]
    env.Depends(targets, '#build/bin/sandesh' + env['PROGSUFFIX'])
    return env.SandeshC(targets, file)

# SandeshGenPy Methods
def SandeshPyBuilder(target, source, env):
    opath = target[0].dir.path
    py_opath = os.path.dirname(opath)
    wait_for_sandesh_install(env)
    code = subprocess.call(env['SANDESH'] + ' --gen py:new_style -I controller/src/ -I src/contrail-common -out ' +
                           py_opath + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshPy py code generation failed')
    code = subprocess.call(env['SANDESH'] + ' --gen html -I controller/src/ -I src/contrail-common -out ' +
                           opath + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshPy html generation failed')

def SandeshSconsEnvPyFunc(env):
    pybuild = Builder(action = Action(SandeshPyBuilder,'SandeshPyBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshPy' : pybuild})

def SandeshGenPyFunc(env, path, target='', gen_py=True):
    SandeshSconsEnvPyFunc(env)
    modules = [
        '__init__.py',
        'constants.py',
        'ttypes.py',
        'http_request.py']
    basename = Basename(path)
    path_split = basename.rsplit('/',1)
    if len(path_split) == 2:
        mod_dir = path_split[1] + '/'
    else:
        mod_dir = path_split[0] + '/'
    if gen_py:
        targets = [target + 'gen_py/' + mod_dir + module for module in modules]
    else:
        targets = [target + mod_dir + module for module in modules]

    env.Depends(targets, '#build/bin/sandesh' + env['PROGSUFFIX'])
    return env.SandeshPy(targets, path)

# Golang Methods for CNI
def GoCniFunc(env, filepath, target=''):
    # get dependencies
    goenv = os.environ.copy()
    goenv['GOROOT'] = env.Dir('#/third_party/go').abspath
    goenv['GOPATH'] = env.Dir('#/third_party/cni_go_deps').abspath
    goenv['GOBIN'] = env.Dir(env['TOP'] + '/container/cni/bin').abspath
    cni_path = env.Dir('#/' + env.Dir('.').srcnode().path).abspath
    go_cmd = goenv['GOROOT'] + '/bin/go '
    try:
        cmd = 'cd ' + cni_path + ';'
        cmd += go_cmd + 'install'
        code = subprocess.call(cmd, shell=True, env=goenv)
    except Exception as e:
        print(str(e))
    return env['TOP'] + '/container/cni/bin/' + filepath

# ThriftGenCpp Methods
ThriftServiceRe = re.compile(r'service\s+(\S+)\s*{', re.M)
def ThriftServicesFunc(node):
    contents = node.get_text_contents()
    return ThriftServiceRe.findall(contents)

def ThriftSconsEnvFunc(env, asynch):
    opath = env.Dir('.').abspath
    thriftcmd = os.path.join(env.Dir(env['TOP_BIN']).abspath, 'thrift')
    if asynch:
        lstr = thriftcmd + ' --gen cpp:async -o ' + opath + ' $SOURCE'
    else:
        lstr = thriftcmd + ' --gen cpp -o ' + opath + ' $SOURCE'
    cppbuild = Builder(action = lstr)
    env.Append(BUILDERS = {'ThriftCpp' : cppbuild})

def ThriftGenCppFunc(env, file, asynch):
    ThriftSconsEnvFunc(env, asynch)
    suffixes = ['_types.h', '_constants.h', '_types.cpp', '_constants.cpp']
    basename = Basename(file)
    base_files = map(lambda s: 'gen-cpp/' + basename + s, suffixes)
    services = ThriftServicesFunc(env.File(file))
    service_cfiles = map(lambda s: 'gen-cpp/' + s + '.cpp', services)
    service_hfiles = map(lambda s: 'gen-cpp/' + s + '.h', services)
    targets = base_files + service_cfiles + service_hfiles
    env.Depends(targets, '#build/bin/thrift' + env['PROGSUFFIX'])
    return env.ThriftCpp(targets, file)

def ThriftPyBuilder(source, target, env, for_signature):
    output_dir = os.path.dirname(os.path.dirname(str(target[0])))
    return ('%s --gen py:new_style,utf8strings -I src/ -out %s %s' %
            (os.path.join(env.Dir(env['TOP_BIN']).abspath, 'thrift'), output_dir, source[0]))

def ThriftSconsEnvPyFunc(env):
    pybuild = Builder(generator = ThriftPyBuilder)
    env.Append(BUILDERS = {'ThriftPy' : pybuild})

def ThriftGenPyFunc(env, path, target=''):
    modules = [
        '__init__.py',
        'constants.py',
        'ttypes.py']
    basename = Basename(path)
    path_split = basename.rsplit('/', 1)
    if len(path_split) == 2:
        mod_dir = path_split[1] + '/'
    else:
        mod_dir = path_split[0] + '/'
    if target[-1] != '/':
        target += '/'
    targets = map(lambda module: target + 'gen_py/' + mod_dir + module, modules)
    env.Depends(targets, '#build/bin/thrift' + env['PROGSUFFIX'])
    return env.ThriftPy(targets, path)

def IFMapBuilderCmd(source, target, env, for_signature):
    output = Basename(source[0].abspath)
    return '%s -f -g ifmap-backend -o %s %s' % (env.File('#src/contrail-api-client/generateds/generateDS.py').abspath, output, source[0])

def IFMapTargetGen(target, source, env):
    suffixes = ['_types.h', '_types.cc', '_parser.cc',
                '_server.cc', '_agent.cc']
    basename = Basename(source[0].abspath)
    targets = [basename + x for x in suffixes]
    return targets, source

def CreateIFMapBuilder(env):
    builder = Builder(generator = IFMapBuilderCmd,
                      src_suffix = '.xsd',
                      emitter = IFMapTargetGen)
    env.Append(BUILDERS = { 'IFMapAutogen' : builder})

def DeviceAPIBuilderCmd(source, target, env, for_signature):
    output = Basename(source[0].abspath)
    return './src/contrail-api-client/generateds/generateDS.py -f -g device-api -o %s %s' % (output, source[0])

def DeviceAPITargetGen(target, source, env):
    suffixes = []
    basename = Basename(source[0].abspath)
    targets = map(lambda x: basename + x, suffixes)
    return targets, source

def CreateDeviceAPIBuilder(env):
    builder = Builder(generator = DeviceAPIBuilderCmd,
                      src_suffix = '.xsd')
    env.Append(BUILDERS = { 'DeviceAPIAutogen' : builder})

def TypeBuilderCmd(source, target, env, for_signature):
    output = Basename(source[0].abspath)
    return '%s -f -g type -o %s %s' % (env.File('#src/contrail-api-client/generateds/generateDS.py').abspath, output, source[0])

def TypeTargetGen(target, source, env):
    suffixes = ['_types.h', '_types.cc', '_parser.cc']
    basename = Basename(source[0].abspath)
    targets = [basename + x for x in suffixes]
    return targets, source

def CreateTypeBuilder(env):
    builder = Builder(generator = TypeBuilderCmd,
                      src_suffix = '.xsd',
                      emitter = TypeTargetGen)
    env.Append(BUILDERS = { 'TypeAutogen' : builder})

# Check for unsupported/buggy compilers.
def CheckBuildConfiguration(conf):
    # gcc 4.7.0 generates buggy code when optimization is turned on.
    opt_level = GetOption('opt')
    if ((opt_level == 'production' or opt_level == 'profile') and \
        (conf.env['CC'].endswith("gcc") or conf.env['CC'].endswith("g++"))):
        if conf.env['CCVERSION'] == "4.7.0":
            print("Unsupported/Buggy compiler gcc 4.7.0 for building " + \
                  "optimized binaries")
            raise convert_to_BuildError(1)
    # Specific versions of MS C++ compiler are not supported for
    # "production" build.
    if opt_level == 'production' and conf.env['CC'] == 'cl':
        if not VerifyClVersion():
            print("Unsupported MS C++ compiler for building " +
                  "optimized binaries")
            raise convert_to_BuildError(1)
    return conf.Finish()

def VerifyClVersion():
    # Microsoft C++ 19.00.24210 is known to produce incorrectly working Agent
    # in "production" build as it is described in bug #1802130.
    # Undesired behaviour has been mitigated by code change in Agent.
    # However, this compiler version (and all older) are considered "unsafe"
    # and luckily there's no reason to use them. MS VC 2015 Update 3 provides
    # newer version of the compiler.
    minimum_cl_version = [19, 0, 24215, 1]

    # Unfortunately there's no better way to check the CL version
    process = subprocess.run(['cl.exe'], capture_output=True, encoding='ASCII')
    regex_string = "Microsoft \(R\) C/C\+\+ [\s\w]*Version ([0-9]+)\." +\
                   "([0-9]+)\.([0-9]+)(?:\.([0-9]+))?[\s\w]*"
    regex_parser = re.compile(regex_string)
    match = regex_parser.match(process.stderr)
    our_cl_version = [int(x or 0) for x in (match.groups())]
    return our_cl_version >= minimum_cl_version

def PyTestSuiteCov(target, source, env):
    for test in source:
        log = test.name + '.log'
        if env['env_venv']:
            venv = env['env_venv']
            try:
                env['_venv'][log] = venv[0]
            except KeyError:
                env['_venv'] = {log: venv[0]}
        logfile = test.path + '.log'
        RunUnitTest(env, [env.File(logfile)], [env.File(test)], 800)
    return None

def UseSystemBoost(env):
    """
    Whether to use the boost library provided by the system.
    """
    from distutils.version import LooseVersion
    (distname, version, _) = env.GetPlatformInfo()
    exclude_dist = {
        'Ubuntu': '14.04',
        'debian': '8',
        'raspbian': '8',
        'centos': '7.0',
        'CentOS Linux': '7.0',
        'fedora': '20',
        'Fedora': '20',
        'SUSE Linux Enterprise Desktop ': '12',
        'SUSE Linux Enterprise Server ': '12',
        'redhat': '7.0',
        'Red Hat Enterprise Linux Server': '7.0',
    }
    v_required = exclude_dist.get(distname)
    if v_required and LooseVersion(version) >= LooseVersion(v_required):
        return True
    return False

def UseSystemTBB(env):
    """ Return True whenever the compilation uses the built-in version of the
    Thread-Building Block library instead of compiling it.
    """
    from distutils.version import LooseVersion
    systemTBBdict = {
        'Ubuntu': '14.04',
        'debian': '8',
        'raspbian': '8',
        'centos': '7.0',
        'CentOS Linux': '7.0',
        'fedora': '20',
        'Fedora': '20',
        'redhat': '7.0',
        'Red Hat Enterprise Linux Server': '7.0',
    }
    (distname, version, _) = env.GetPlatformInfo()
    v_required = systemTBBdict.get(distname)
    if v_required and LooseVersion(version) >= LooseVersion(v_required):
        return True
    return False

def UseCassandraCql(env):
    """
    Whether to use CQL interface to cassandra
    """
    from distutils.version import LooseVersion
    cassandra_cql_supported = {
        'Ubuntu': '14.04',
        'debian': '8',
        'raspbian': '8',
        'centos': '7.1',
        'CentOS Linux': '7.1',
        'redhat': '7.0',
        'Red Hat Enterprise Linux Server': '7.0',
    }
    (distname, version, _) = env.GetPlatformInfo()
    v_required = cassandra_cql_supported.get(distname)
    if v_required and LooseVersion(version) >= LooseVersion(v_required):
        return True
    return False

def CppDisableExceptions(env):
    if not UseSystemBoost(env) and sys.platform != 'win32':
        env.AppendUnique(CCFLAGS='-fno-exceptions')

def CppEnableExceptions(env):
    cflags = env['CCFLAGS']
    if '-fno-exceptions' in cflags:
        cflags.remove('-fno-exceptions')
        env.Replace(CCFLAGS = cflags)

def PlatformDarwin(env):
    cmd = 'sw_vers | \grep ProductVersion'
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, shell=True)
    ver, stderr = p.communicate()
    ver = ver.rstrip('\n')
    ver = re.match(r'ProductVersion:\s+(\d+\.\d+)', ver).group(1)
    if float(ver) >= 10.9:
        return

    if not 'SDKROOT' in env['ENV']:

        # Find Mac SDK version.
        sdk = '/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX' + ver + '.sdk'
        env['ENV']['SDKROOT'] = sdk

    if not 'DEVELOPER_BIN_DIR' in env['ENV']:
        env['ENV']['DEVELOPER_BIN_DIR'] = '/Applications/Xcode.app/Contents/Developer/usr/bin'

    env.AppendENVPath('PATH', env['ENV']['DEVELOPER_BIN_DIR'])

    if not 'DT_TOOLCHAIN_DIR' in env['ENV']:
        env['ENV']['DT_TOOLCHAIN_DIR'] = '/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain'

    env.AppendENVPath('PATH', env['ENV']['DT_TOOLCHAIN_DIR'] + '/usr/bin')

    env['CXX'] = 'clang++'
    env.Append(CPPPATH = [env['ENV']['SDKROOT'] + '/usr/include',
#                         env['ENV']['SDKROOT'] + '/usr/include/c++/v1',
                          env['ENV']['SDKROOT'] + '/usr/include/c++/4.2.1',
                          ])
#   env.Append(LIBPATH = env['ENV']['SDKROOT'] + '/usr/lib')
#   env.Append(LIBS = 'c++.1')

def build_maven(env, target, source, path):
    mvn_target = env.Command(target, source, 'cd ' + str(path) + ' && mvn install')
    env.AlwaysBuild(mvn_target)
    env.Default(mvn_target)
    return mvn_target

# Decide whether to use parallel build, and determine value to use/set.
# Controlled by environment var CONTRAIL_BUILD_JOBS:
#    if set to 'no' or 1, then no parallel build
#    if set to an integer, use it blindly
#    if set to any other string (e.g., 'yes'):
#        compute a reasonable value based on number of CPU's and load avg
#
def determine_job_value():
    if 'CONTRAIL_BUILD_JOBS' not in os.environ: return 1

    v = os.environ['CONTRAIL_BUILD_JOBS']
    if v == 'no': return 1

    try: return int(v)
    except: pass

    try:
        import multiprocessing
        ncpu = multiprocessing.cpu_count()
        ncore = ncpu / 2
    except:
        ncore = 1

    (one,five,_) = os.getloadavg()
    avg_load = int(one + five / 2)
    avail = (ncore - avg_load) * 3 / 2
    print("scons: available jobs = %d" % avail)
    return avail

class UnitTestsCollector(object):
    """Unit Test collector and processor

    A small class that abstracts collecting unit tests and their metadata.
    It is used to generate a list of tests from the targets passed to scons,
    to be used by the CI test runner to better report failures.
    """

    def __init__(self):
        self.tests = []

    def add_test(self, node_path, xml_path, log_path):
        self.tests += [{"node_path": node_path, "xml_path": xml_path,
		       "log_path": log_path}]

def SetupBuildEnvironment(conf):
    AddOption('--optimization', '--opt', dest = 'opt',
              action='store', default='debug',
              choices = ['debug', 'production', 'coverage', 'profile', 'valgrind'],
              help='optimization level: [debug|production|coverage|profile|valgrind]')

    AddOption('--target', dest = 'target',
              action='store', default='x86_64',
              choices = ['i686', 'x86_64', 'armhf'])

    AddOption('--cpu', dest = 'cpu',
                action='store',
                choices = ['native', 'hsw', 'snb', 'ivb'])

    AddOption('--root', dest = 'install_root', action='store')
    AddOption('--prefix', dest = 'install_prefix', action='store')
    AddOption('--pytest', dest = 'pytest', action='store')
    AddOption('--without-dpdk', dest = 'without-dpdk',
              action='store_true', default=False)
    AddOption('--describe-tests', dest = 'describe-tests',
              action='store_true', default=False)

    env = CheckBuildConfiguration(conf)

    env.AddMethod(PlatformExclude, "PlatformExclude")
    env.AddMethod(GetPlatformInfo, "GetPlatformInfo")

    # Let's decide how many jobs (-jNN) we should use.
    nj = GetOption('num_jobs')
    if nj == 1:
        # Should probably check for CLI over-ride of -j1 (i.e., do not
        # assume 1 means -j not specified).
        nj = determine_job_value()
        if nj > 1:
            print("scons: setting jobs (-j) to %d" % nj)
            SetOption('num_jobs', nj)
            env['NUM_JOBS'] = nj

    env['OPT'] = GetOption('opt')
    env['TARGET_MACHINE'] = GetOption('target')
    env['CPU_TYPE'] = GetOption('cpu')
    env['INSTALL_PREFIX'] = GetOption('install_prefix')
    env['INSTALL_BIN'] = ''
    env['INSTALL_SHARE'] = ''
    env['INSTALL_LIB'] = ''
    env['INSTALL_INIT'] = ''
    env['INSTALL_INITD'] = ''
    env['INSTALL_SYSTEMD'] = ''
    env['INSTALL_CONF'] = ''
    env['INSTALL_SNMP_CONF'] = ''
    env['INSTALL_EXAMPLE'] = ''
    env['PYTHON_INSTALL_OPT'] = ''
    env['INSTALL_DOC'] = ''

    install_root = GetOption('install_root')
    if install_root:
        env['INSTALL_BIN'] = install_root
        env['INSTALL_SHARE'] = install_root
        env['INSTALL_LIB'] = install_root
        env['INSTALL_INIT'] = install_root
        env['INSTALL_INITD'] = install_root
        env['INSTALL_SYSTEMD'] = install_root
        env['INSTALL_CONF'] = install_root
        env['INSTALL_SNMP_CONF'] = install_root
        env['INSTALL_EXAMPLE'] = install_root
        env['INSTALL_DOC'] = install_root
        env['PYTHON_INSTALL_OPT'] = '--root ' + install_root + ' '

    install_prefix = GetOption('install_prefix')
    if install_prefix:
        env['INSTALL_BIN'] += install_prefix
        env['INSTALL_SHARE'] += install_prefix
        env['INSTALL_LIB'] += install_prefix
        env['INSTALL_INIT'] += install_prefix
        env['INSTALL_INITD'] += install_prefix
        env['INSTALL_SYSTEMD'] += install_prefix
        env['PYTHON_INSTALL_OPT'] += '--prefix ' + install_prefix + ' '
    elif install_root:
        env['INSTALL_BIN'] += '/usr'
        env['INSTALL_SHARE'] += '/usr'
        env['INSTALL_LIB'] += '/usr'
        env['PYTHON_INSTALL_OPT'] += '--prefix /usr '
    else:
        env['INSTALL_BIN'] += '/usr/local'

    env['INSTALL_BIN'] += '/bin'
    env['INSTALL_SHARE'] += '/share'
    env['INSTALL_LIB'] += '/lib'
    env['INSTALL_INIT'] += '/etc/init'
    env['INSTALL_INITD'] += '/etc/init.d'
    env['INSTALL_SYSTEMD'] += '/lib/systemd/system'
    env['INSTALL_CONF'] += '/etc/contrail'
    env['INSTALL_SNMP_CONF'] += '/etc/snmp'
    env['INSTALL_EXAMPLE'] += '/usr/share/contrail'
    env['INSTALL_DOC'] += '/usr/share/doc'

    # Sometimes we don't need or want full CLI's
    if WantQuietOutput():
        env['ARCOMSTR'] = 'AR $TARGET'
        env['CCCOMSTR'] = 'CC $TARGET'
        env['CXXCOMSTR'] = 'C++ $TARGET'
        env['INSTALLSTR'] = 'Install $SOURCE -> $TARGET'
        env['LINKCOMSTR'] = 'LD $TARGET'
        env['RANLIBCOMSTR'] = 'RANLIB $TARGET'
        env['SHCCCOMSTR'] = 'CC $TARGET [shared]'
        env['SHCXXCOMSTR'] = 'C++ $TARGET [shared]'
        env['SHDLINKCOMSTR'] = 'LD $TARGET [shared]'

    distribution = env.GetPlatformInfo()[0]

    if distribution in ["Ubuntu", "debian", "raspbian"]:
        env['PYTHON_INSTALL_OPT'] += '--install-layout=deb '

    if distribution == 'Darwin':
        PlatformDarwin(env)
        env['ENV_SHLIB_PATH'] = 'DYLD_LIBRARY_PATH'
    else:
        env['ENV_SHLIB_PATH'] = 'LD_LIBRARY_PATH'

    if env.get('TARGET_MACHINE') == 'i686':
        env.Append(CCFLAGS = '-march=' + 'i686')
    elif env.get('TARGET_MACHINE') == 'armhf' or platform.machine().startswith('arm'):
        env.Append(CCFLAGS=['-DTBB_USE_GCC_BUILTINS=1', '-D__TBB_64BIT_ATOMICS=0'])

    env['TOP_BIN'] = '#build/bin'
    env['TOP_INCLUDE'] = '#build/include'
    env['TOP_LIB'] = '#build/lib'

    pytest = GetOption('pytest')
    if pytest:
        env['PYTESTARG'] = pytest
    else:
        env['PYTESTARG'] = None
    env.tests = UnitTestsCollector()

    # Store path to sandesh compiler in the env
    env['SANDESH'] = os.path.join(env.Dir(env['TOP_BIN']).path, 'sandesh' + env['PROGSUFFIX'])

    # Store the hostname in env.
    if 'HOSTNAME' not in env:
        env['HOSTNAME'] = platform.node()

    # Store repo projects in the environment
    proc = subprocess.Popen('repo list', stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell='True')
    repo_out, err = proc.communicate()
    repo_lines = repo_out.splitlines()
    repo_list = {}
    for l in repo_lines:
        (path,repo) = l.split(" : ")
        repo_list[path] = repo
    env['REPO_PROJECTS'] = repo_list

    if sys.platform == 'win32':
        env.Append(CCFLAGS = '/Iwindows/inc')
        env.Append(CCFLAGS = '/D_WINDOWS')

        # Set Windows Server 2016 as target system
        env.Append(CCFLAGS = '/D_WIN32_WINNT=0x0A00')
        # Set exception handling model
        env.Append(CCFLAGS = '/EHsc')
        # Disable min/max macros to avoid conflicts
        env.Append(CCFLAGS = '/DNOMINMAX')
        # Disable GDI to avoid conflicts with macros
        env.Append(CCFLAGS = '/DNOGDI')
        # Disable MSVC paranoid warnings
        env.Append(CCFLAGS = ['/D_SCL_SECURE_NO_WARNINGS', '/D_CRT_SECURE_NO_WARNINGS'])
        # Stop Windows.h from including a lot of useless header files
        env.Append(CCFLAGS = '/DWIN32_LEAN_AND_MEAN')

    opt_level = env['OPT']
    if opt_level == 'production':
        if sys.platform == 'win32':
            env['VS_BUILDMODE'] = 'Release'
            # Enable full compiler optimization
            env.Append(CCFLAGS = '/Ox')
            # Enable multithreaded release dll build
            env.Append(CCFLAGS = '/MD')
            # Enable linker whole program optimization
            env.Append(LINKFLAGS = '/LTCG')
        else:
            env.Append(CCFLAGS = '-O3')
        env['TOP'] = '#build/production'
    elif opt_level == 'debug':
        if sys.platform == 'win32':
            env['VS_BUILDMODE'] = 'Debug'
            # Enable runtime checks and disable optimization
            env.Append(CCFLAGS = '/RTC1')
            # Enable multithreaded debug dll build and define _DEBUG
            env.Append(CCFLAGS = '/MDd')
        else:
            env.Append(CCFLAGS = ['-O0', '-DDEBUG'])
        env['TOP'] = '#build/debug'
    elif opt_level == 'profile':
        # Enable profiling through gprof
        env.Append(CCFLAGS = ['-O3', '-DDEBUG', '-pg'])
        env.Append(LINKFLAGS = ['-pg'])
        env['TOP'] = '#build/profile'
    elif opt_level == 'coverage':
        env.Append(CCFLAGS = ['-O0', '--coverage'])
        env['TOP'] = '#build/coverage'
        env.Append(LIBS = 'gcov')
    elif opt_level == 'valgrind':
        env.Append(CCFLAGS = ['-O0', '-DDEBUG'])
        env['TOP'] = '#build/valgrind'

    if not "CONTRAIL_COMPILE_WITHOUT_SYMBOLS" in os.environ:
        if sys.platform == 'win32':
            # Enable full symbolic debugging information
            env.Append(CCFLAGS = '/Z7')
            env.Append(LINKFLAGS = '/DEBUG')
        else:
            env.Append(CCFLAGS = '-g')
            env.Append(LINKFLAGS = '-g')

    env.Append(BUILDERS = {'PyTestSuite': PyTestSuite })
    env.Append(BUILDERS = {'TestSuite': TestSuite })
    env.Append(BUILDERS = {'UnitTest': UnitTest})
    env.Append(BUILDERS = {'GenerateBuildInfoCode': GenerateBuildInfoCode})
    env.Append(BUILDERS = {'GenerateBuildInfoPyCode': GenerateBuildInfoPyCode})
    env.Append(BUILDERS = {'GenerateBuildInfoCCode': GenerateBuildInfoCCode})

    env.Append(BUILDERS = {'setup_venv': setup_venv})
    env.Append(BUILDERS = {'venv_add_pip_pkg': venv_add_pip_pkg })
    env.Append(BUILDERS = {'venv_add_build_pkg': venv_add_build_pkg })
    env.Append(BUILDERS = {'build_maven': build_maven })

    # A few methods to enable/support UTs and BUILD_ONLY
    env.AddMethod(GetVncAPIPkg, 'GetVncAPIPkg')
    env.AddMethod(SetupPyTestSuite, 'SetupPyTestSuite' )
    env.AddMethod(SetupPyTestSuiteWithDeps, 'SetupPyTestSuiteWithDeps' )

    env.AddMethod(ExtractCppFunc, "ExtractCpp")
    env.AddMethod(ExtractCFunc, "ExtractC")
    env.AddMethod(ExtractHeaderFunc, "ExtractHeader")
    env.AddMethod(GetBuildVersion, "GetBuildVersion")
    env.AddMethod(ProtocGenDescFunc, "ProtocGenDesc")
    env.AddMethod(ProtocGenCppFunc, "ProtocGenCpp")
    env.AddMethod(ProtocGenCppMapTgtDirFunc, "ProtocGenCppMapTgtDir")
    env.AddMethod(SandeshGenOnlyCppFunc, "SandeshGenOnlyCpp")
    env.AddMethod(SandeshGenCppFunc, "SandeshGenCpp")
    env.AddMethod(SandeshGenCFunc, "SandeshGenC")
    env.AddMethod(SandeshGenPyFunc, "SandeshGenPy")
    env.AddMethod(SandeshGenDocFunc, "SandeshGenDoc")
    env.AddMethod(GoCniFunc, "GoCniBuild")
    env.AddMethod(ThriftGenCppFunc, "ThriftGenCpp")
    ThriftSconsEnvPyFunc(env)
    env.AddMethod(ThriftGenPyFunc, "ThriftGenPy")
    CreateIFMapBuilder(env)
    CreateTypeBuilder(env)
    CreateDeviceAPIBuilder(env)

    PyTestSuiteCovBuilder = Builder(action = PyTestSuiteCov)
    env.Append(BUILDERS = {'PyTestSuiteCov' : PyTestSuiteCovBuilder})

    # Not used?
    symlink_builder = Builder(action = "cd ${TARGET.dir} && " +
                              "ln -s ${SOURCE.file} ${TARGET.file}")
    env.Append(BUILDERS = {'Symlink': symlink_builder})

    env.AddMethod(UseSystemBoost, "UseSystemBoost")
    env.AddMethod(UseSystemTBB, "UseSystemTBB")
    env.AddMethod(UseCassandraCql, "UseCassandraCql")
    env.AddMethod(CppDisableExceptions, "CppDisableExceptions")
    env.AddMethod(CppEnableExceptions, "CppEnableExceptions")

    return env
# SetupBuildEnvironment

def resolve_alias_dependencies(env, aliases):
    """Given alias string, return all its leaf dependencies.

    SCons aliases can depend on SCons nodes, or other aliases. Recursively
    resolve aliases to actual dependencies.
    """
    nodes = set()
    for alias in aliases:
        assert isinstance(alias, SCons.Node.Alias.Alias)
        for node in alias.children():
            if isinstance(node, SCons.Node.Alias.Alias):
                nodes |= (resolve_alias_dependencies(env, [node]))
            else:
                nodes.add(node)
    return nodes

def DescribeTests(env, targets):
    """Given a set of targets, print out JSON Lines encoded tests."""
    node_paths = []
    for target in targets:
        scons_aliases = env.arg2nodes(target)
        nodes = resolve_alias_dependencies(env, scons_aliases)
        node_paths += [n.abspath for n in nodes]

    matched_tests = []
    for test in env.tests.tests:
        path = test['node_path']
        if path in node_paths:
            test['matched'] = True
            matched_tests += [test]
            node_paths.remove(path)

    for test in matched_tests:
        print(json.dumps(test))

    for node_path in node_paths:
        dangling_node = {"node_path": node_path, "matched": False}
        print(json.dumps(dangling_node))
