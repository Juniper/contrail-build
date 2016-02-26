#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

import os
import re
from SCons.Builder import Builder
from SCons.Action import Action
from SCons.Errors import convert_to_BuildError
from SCons.Script import AddOption, GetOption
import json
import SCons.Util
import subprocess
import sys
import time
import commands
import platform

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
    if env['ENV'].has_key('BUILD_ONLY'):
        return
    import subprocess

    if env['ENV'].has_key('CONTRAIL_UT_TEST_TIMEOUT'):
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
    # Use gprof unless NO_HEAPCHECK is set or in CentOS
    heap_check = ShEnv.has_key('NO_HEAPCHECK') == False
    if heap_check:
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
        print test + '\033[91m' + " TIMEOUT" + '\033[0m'
        raise convert_to_BuildError(code)
        return

    if code == 0:
        print test + '\033[94m' + " PASS" + '\033[0m'
    else:
        logfile.write('[  FAILED  ] ')
        if code < 0:
            logfile.write('Terminated by signal: ' + str(-code) + '\n')
        else:
            logfile.write('Program returned ' + str(code) + '\n')
        print test + '\033[91m' + " FAIL" + '\033[0m'
        raise convert_to_BuildError(code)

def TestSuite(env, target, source):
    if len(source):
        for test in env.Flatten(source):
            # UnitTest() may have tagged tests with skip_run attribute
            if getattr( test.attributes, 'skip_run', False ): continue
            log = test.abspath + '.log'
            cmd = env.Command(log, test, RunUnitTest)
            env.AlwaysBuild(cmd)
            env.Alias(target, cmd)
        return target

def setup_venv(env, target, venv_name, path=None):
    p = path
    if not p:
        ws_link = os.environ.get('CONTRAIL_REPO')
        if ws_link: p = ws_link + "/build/" + env['OPT']
        else: p = env.Dir(env['TOP']).abspath

    tdir = '/tmp/cache/%s/systemless_test' % os.environ['USER']
    shell_cmd = ' && '.join ([
        'cd %s' % p,
        'mkdir %s' % tdir,
        '[ -f %s/ez_setup-0.9.tar.gz ] || curl -o %s/ez_setup-0.9.tar.gz https://pypi.python.org/packages/source/e/ez_setup/ez_setup-0.9.tar.gz' % (tdir,tdir),
        '[ -d ez_setup-0.9 ] || tar xzf %s/ez_setup-0.9.tar.gz' % tdir,
        '[ -f %s/redis-2.6.13.tar.gz ] || (cd %s && wget https://redis.googlecode.com/files/redis-2.6.13.tar.gz)' % (tdir,tdir),
        '[ -d ../redis-2.6.13 ] || (cd .. && tar xzf %s/redis-2.6.13.tar.gz)' % tdir,
        '[ -f testroot/bin/redis-server ] || ( cd ../redis-2.6.13 && make PREFIX=%s/testroot install)' % p,
        '[ -f %s/Python-2.7.3.tar.bz2 ] || (cd %s && wget --no-check-certificate http://www.python.org/ftp/python/2.7.3/Python-2.7.3.tar.bz2)' % (tdir,tdir),
        '[ -d ../Python-2.7.3 ] || (cd .. && tar xjvf %s/Python-2.7.3.tar.bz2)' % tdir,
        '[ -f testroot/bin/python ] || ( cd ../Python-2.7.3 && ./configure --prefix=%s/testroot && make install ) && ( cd ez_setup-0.9 && ../testroot/bin/python setup.py install)' % p,
        '[ -f %s/virtualenv-1.10.1.tar.gz ] || curl -o %s/virtualenv-1.10.1.tar.gz https://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.10.1.tar.gz' % (tdir,tdir),
        '[ -d virtualenv-1.10.1 ] || tar xzvf %s/virtualenv-1.10.1.tar.gz' % tdir,
        'testroot/bin/python virtualenv-1.10.1/virtualenv.py --python=testroot/bin/python %s',
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

    tdir = '/tmp/cache/%s/systemless_test' % os.environ['USER']
    cmd = env.Command(targets, None, '/bin/bash -c "source %s/bin/activate; pip install --download-cache=%s %s"' %
                      (venv._path, tdir, ' '.join(pkg_list)))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def venv_add_build_pkg(env, v, pkg):
    cmd = []
    venv = env[v[0]]
    for p in pkg:
        t = 'build-' + os.path.basename (p)
        cmd += env.Command (t, '',
       '/bin/bash -c "source %s/bin/activate; pushd %s && python setup.py install; popd"' % (
              venv._path, p))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def PyTestSuite(env, target, source, venv=None):
    if env['ENV'].has_key('BUILD_ONLY'):
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
    if sys.platform != 'darwin' and env.get('OPT') != 'coverage' and \
           not env['ENV'].has_key('NO_HEAPCHECK') and \
           env.get('OPT') != 'valgrind':
        test_env.Append(LIBPATH = '#/build/lib')
        test_env.Append(LIBS = ['tcmalloc'])
    test_exe_list = test_env.Program(name, sources)
    if test_env.PlatformExclude(**kwargs):
        for t in test_exe_list: t.attributes.skip_run = True
    return test_exe_list

def GenerateBuildInfoCode(env, target, source, path):
    env.Command(target=target, source=source, action=BuildInfoAction)
    return

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
    build_time = unicode(datetime.datetime.utcnow())

    # Fetch git version
    repo_path = env.Dir('#controller').path
    cmd = 'cd ' + repo_path + '; git log --oneline | head -1 | awk \'{ print $1 }\''
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         shell='True')
    build_git_info, err = p.communicate()
    build_git_info = build_git_info.strip()

    # Fetch build version
    file_path = env.File('#/controller/src/base/version.info').abspath
    f = open(file_path)
    build_version = (f.readline()).strip()

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

    h_file = file(os.path.join(build_dir, 'buildinfo.h'), 'w')
    h_file.write(h_code)
    h_file.close()

    cc_file = file(os.path.join(build_dir, 'buildinfo.cc'), 'w')
    cc_file.write(cc_code)
    cc_file.close()
    return
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

    c_file = file(os.path.join(build_dir, target[0]), 'w')
    c_file.write(c_code)
    c_file.close()
    return
#end GenerateBuildInfoCCode

def GenerateBuildInfoPyCode(env, target, source, path):
    import os
    import subprocess

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
    build_time = unicode(datetime.datetime.utcnow())

    # Fetch git version
    repo_path = env.Dir('#controller').path
    p = subprocess.Popen('cd ' + repo_path + ' && git log --oneline | head -1 | awk \'{ print $1 }\'',
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell='True')
    build_git_info, err = p.communicate()
    build_git_info = build_git_info.strip()

    # Fetch build version
    file_path = env.Dir('#').abspath + '/controller/src/base/version.info'
    f = open(file_path)
    build_version = (f.readline()).strip()

    # build json string containing build information
    build_info = "{\\\"build-info\\\" : [{\\\"build-version\\\" : \\\"" + str(build_version) + "\\\", \\\"build-time\\\" : \\\"" + str(build_time) + "\\\", \\\"build-user\\\" : \\\"" + build_user + "\\\", \\\"build-hostname\\\" : \\\"" + build_host + "\\\", "
    py_code ="build_info = \""+ build_info + "\";\n"
    py_file = file(path + '/buildinfo.py', 'w')
    py_file.write(py_code)
    py_file.close()

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
    protoc = env.WhereIs('protoc')
    protoc_cmd = protoc + ' --descriptor_set_out=' + \
        str(target[0]) + ' --include_imports ' + \
        str(source[0])
    print protoc_cmd
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
    protoc = env.WhereIs('protoc')
    protoc_cmd = protoc + ' --proto_path=/usr/include/ ' + \
        '--proto_path=controller/src/ --proto_path=' + \
        spath + ' --cpp_out=' + str(env.Dir(env['TOP'])) + ' ' + \
        str(source[0])
    print protoc_cmd
    code = subprocess.call(protoc_cmd, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(
            'protobuf code generation failed')

def ProtocSconsEnvCppFunc(env):
    cppbuild = Builder(action = ProtocCppBuilder)
    env.Append(BUILDERS = {'ProtocCpp' : cppbuild})

def ProtocGenCppFunc(env, file):
    ProtocSconsEnvCppFunc(env)
    suffixes = ['.pb.h',
                '.pb.cc'
               ]
    basename = Basename(file)
    targets = map(lambda suffix: basename + suffix, suffixes)
    return env.ProtocCpp(targets, file)

class SandeshWarning(SCons.Warnings.Warning):
    pass

class SandeshCodeGeneratorError(SandeshWarning):
    pass

# SandeshGenOnlyCpp Methods
def SandeshOnlyCppBuilder(target, source, env):
    sname = os.path.splitext(source[0].name)[0] # file name w/o .sandesh
    html_cpp_name = os.path.join(target[0].dir.path, sname + '_html.cpp')

    code = subprocess.call(env['SANDESH'] + ' --gen cpp -I controller/src/ -out ' +
                           target[0].dir.path + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshOnlyCpp code generation failed')
    os.system("echo \"int " + sname + "_marker = 0;\" >> " + html_cpp_name)

def SandeshSconsEnvOnlyCppFunc(env):
    onlycppbuild = Builder(action = Action(SandeshOnlyCppBuilder,'SandeshOnlyCppBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshOnlyCpp' : onlycppbuild})

def SandeshGenOnlyCppFunc(env, file):
    SandeshSconsEnvOnlyCppFunc(env)
    suffixes = ['_types.h',
        '_types.cpp',
        '_constants.h',
        '_constants.cpp',
        '_html.cpp']
    basename = Basename(file)
    targets = map(lambda suffix: basename + suffix, suffixes)
    env.Depends(targets, '#build/bin/sandesh')
    return env.SandeshOnlyCpp(targets, file)

# SandeshGenCpp Methods
def SandeshCppBuilder(target, source, env):
    opath = target[0].dir.path
    sname = os.path.join(opath, os.path.splitext(source[0].name)[0])

    code = subprocess.call(env['SANDESH'] + ' --gen cpp --gen html -I controller/src/ -I tools -out '
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
    os.system("echo \"namespace {\"" + " >> " + cname)
    os.system("(cd " + opath + " ; xxd -i " + hname + " >> " + os.path.basename(cname) + " )")
    os.system("echo \"}\"" + " >> " + cname)
    os.system("cat " + tname + " >> " + cname)

def SandeshSconsEnvCppFunc(env):
    cppbuild = Builder(action = Action(SandeshCppBuilder, 'SandeshCppBuilder $SOURCE -> $TARGETS'))
    env.Append(BUILDERS = {'SandeshCpp' : cppbuild})

def SandeshGenCppFunc(env, file):
    SandeshSconsEnvCppFunc(env)
    suffixes = ['_types.h',
        '_types.cpp',
        '_constants.h',
        '_constants.cpp',
        '_html.cpp']
    basename = Basename(file)
    targets = map(lambda suffix: basename + suffix, suffixes)
    env.Depends(targets, '#build/bin/sandesh')
    return env.SandeshCpp(targets, file)

# SandeshGenC Methods
def SandeshCBuilder(target, source, env):
    # We need to trim the /gen-c/ out of the target path
    opath = os.path.dirname(target[0].dir.path)
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
    targets = map(lambda suffix: 'gen-c/' + basename + suffix, suffixes)
    env.Depends(targets, '#build/bin/sandesh')
    return env.SandeshC(targets, file)

# SandeshGenPy Methods
def SandeshPyBuilder(target, source, env):
    opath = target[0].dir.path
    py_opath = os.path.dirname(opath)
    code = subprocess.call(env['SANDESH'] + ' --gen py:new_style -I controller/src/ -I tools -out ' +
                           py_opath + " " + source[0].path, shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'SandeshPy py code generation failed')
    code = subprocess.call(env['SANDESH'] + ' --gen html -I controller/src/ -I tools -out ' +
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
        targets = map(lambda module: target + 'gen_py/' + mod_dir + module,
                      modules)
    else:
        targets = map(lambda module: target + mod_dir + module, modules)

    env.Depends(targets, '#build/bin/sandesh')
    return env.SandeshPy(targets, path)

# ThriftGenCpp Methods
ThriftServiceRe = re.compile(r'service\s+(\S+)\s*{', re.M)
def ThriftServicesFunc(node):
    contents = node.get_text_contents()
    return ThriftServiceRe.findall(contents)

def ThriftSconsEnvFunc(env, async):
    opath = env.Dir('.').abspath
    thriftcmd = env.Dir(env['TOP_BIN']).abspath + '/thrift'
    if async:
        lstr = thriftcmd + ' --gen cpp:async -o ' + opath + ' $SOURCE'
    else:
        lstr = thriftcmd + ' --gen cpp -o ' + opath + ' $SOURCE'
    cppbuild = Builder(action = lstr)
    env.Append(BUILDERS = {'ThriftCpp' : cppbuild})

def ThriftGenCppFunc(env, file, async):
    ThriftSconsEnvFunc(env, async)
    suffixes = ['_types.h', '_constants.h', '_types.cpp', '_constants.cpp']
    basename = Basename(file)
    base_files = map(lambda s: 'gen-cpp/' + basename + s, suffixes)
    services = ThriftServicesFunc(env.File(file))
    service_cfiles = map(lambda s: 'gen-cpp/' + s + '.cpp', services)
    service_hfiles = map(lambda s: 'gen-cpp/' + s + '.h', services)
    targets = base_files + service_cfiles + service_hfiles
    env.Depends(targets, '#/build/bin/thrift')
    return env.ThriftCpp(targets, file)

def ThriftPyBuilder(source, target, env, for_signature):
    output_dir = os.path.dirname(os.path.dirname(str(target[0])))
    return ('%s/thrift --gen py:new_style,utf8strings -I src/ -out %s %s' %
            (env.Dir(env['TOP_BIN']), output_dir, source[0]))

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
    env.Depends(targets, '#/build/bin/thrift')
    return env.ThriftPy(targets, path)

def IFMapBuilderCmd(source, target, env, for_signature):
    output = Basename(source[0].abspath)
    return './tools/generateds/generateDS.py -f -g ifmap-backend -o %s %s' % (output, source[0])

def IFMapTargetGen(target, source, env):
    suffixes = ['_types.h', '_types.cc', '_parser.cc',
                '_server.cc', '_agent.cc']
    basename = Basename(source[0].abspath)
    targets = map(lambda x: basename + x, suffixes)
    return targets, source

def CreateIFMapBuilder(env):
    builder = Builder(generator = IFMapBuilderCmd,
                      src_suffix = '.xsd',
                      emitter = IFMapTargetGen)
    env.Append(BUILDERS = { 'IFMapAutogen' : builder})

def TypeBuilderCmd(source, target, env, for_signature):
    output = Basename(source[0].abspath)
    return './tools/generateds/generateDS.py -f -g type -o %s %s' % (output, source[0])

def TypeTargetGen(target, source, env):
    suffixes = ['_types.h', '_types.cc', '_parser.cc']
    basename = Basename(source[0].abspath)
    targets = map(lambda x: basename + x, suffixes)
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
        if commands.getoutput(conf.env['CC'] + ' -dumpversion') == "4.7.0":
            print "Unsupported/Buggy compiler gcc 4.7.0 for building " + \
                  "optimized binaries"
            raise convert_to_BuildError(1)
    return conf.Finish()

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
        RunUnitTest(env, [env.File(logfile)], [env.File(test)], 400)
    return None

def UseSystemBoost(env):
    """
    Whether to use the boost library provided by the system.
    """
    from distutils.version import LooseVersion
    (distname, version, _) = env.GetPlatformInfo()
    exclude_dist = {
        'Ubuntu': '14.04',
        'raspbian': '8',
        'debian': '8',
        'centos': '7.0',
        'CentOS Linux': '7.0',
        'fedora': '20',
        'Fedora': '20',
        'SUSE Linux Enterprise Server ': '12',
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
        'raspbian': '8',
        'debian': '8',
        'centos': '7.0',
        'CentOS Linux': '7.0',
        'fedora': '20',
        'Fedora': '20',
    }
    (distname, version, _) = env.GetPlatformInfo()
    v_required = systemTBBdict.get(distname)
    if v_required and LooseVersion(version) >= LooseVersion(v_required):
        return True
    return False

def CppDisableExceptions(env):
    if not UseSystemBoost(env):
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
    print "scons: available jobs = %d" % avail
    return avail


def SetupBuildEnvironment(conf):
    AddOption('--optimization', dest = 'opt',
              action='store', default='debug',
              choices = ['debug', 'production', 'coverage', 'profile', 'valgrind'],
              help='optimization level: [debug|production|coverage|profile|valgrind]')

    AddOption('--target', dest = 'target',
              action='store',
              choices = ['i686', 'x86_64'])

    AddOption('--root', dest = 'install_root', action='store')
    AddOption('--prefix', dest = 'install_prefix', action='store')

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
            print "scons: setting jobs (-j) to %d" % nj
            SetOption('num_jobs', nj)
            env['NUM_JOBS'] = nj

    env['OPT'] = GetOption('opt')
    env['TARGET_MACHINE'] = GetOption('target')
    env['INSTALL_PREFIX'] = GetOption('install_prefix')
    env['INSTALL_BIN'] = ''
    env['INSTALL_SHARE'] = ''
    env['INSTALL_LIB'] = ''
    env['INSTALL_INIT'] = ''
    env['INSTALL_INITD'] = ''
    env['INSTALL_CONF'] = ''
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
        env['INSTALL_CONF'] = install_root
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
    env['INSTALL_CONF'] += '/etc/contrail'
    env['INSTALL_EXAMPLE'] += '/usr/share/contrail'
    env['INSTALL_DOC'] += '/usr/share/doc'

    distribution = env.GetPlatformInfo()[0]

    if distribution in ["Ubuntu", "raspbian", "debian"]:
        env['PYTHON_INSTALL_OPT'] += '--install-layout=deb '

    if distribution == 'Darwin':
        PlatformDarwin(env)
        env['ENV_SHLIB_PATH'] = 'DYLD_LIBRARY_PATH'
    else:
        env['ENV_SHLIB_PATH'] = 'LD_LIBRARY_PATH'

    if env.get('TARGET_MACHINE') == 'i686':
        env.Append(CCFLAGS = '-march=' + 'i686')

    env['TOP_BIN'] = '#build/bin'
    env['TOP_INCLUDE'] = '#build/include'
    env['TOP_LIB'] = '#build/lib'

    # Store path to sandesh compiler in the env
    env['SANDESH'] = os.path.join(env.Dir(env['TOP_BIN']).path, 'sandesh')

    # Store the hostname in env.
    try:
        build_host = env['HOSTNAME'] if 'HOSTNAME' in env else os.environ['HOSTNAME']
    except KeyError:
        build_host = os.uname()[1]
    env['HOSTNAME'] = build_host

    # Store repo projects in the environment
    proc = subprocess.Popen('repo list', stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell='True')
    repo_out, err = proc.communicate()
    repo_lines = repo_out.splitlines()
    repo_list = {}
    for l in repo_lines:
        (path,repo) = l.split(" : ")
        repo_list[path] = repo
    env['REPO_PROJECTS'] = repo_list

    opt_level = env['OPT']
    if opt_level == 'production':
        env.Append(CCFLAGS = '-g -O3')
        env['TOP'] = '#build/production'
    elif opt_level == 'debug':
        env.Append(CCFLAGS = ['-g', '-O0', '-DDEBUG'])
        env['TOP'] = '#build/debug'
    elif opt_level == 'profile':
        # Enable profiling through gprof
        env.Append(CCFLAGS = ['-g', '-O3', '-DDEBUG', '-pg'])
        env.Append(LINKFLAGS = ['-pg'])
        env['TOP'] = '#build/profile'
    elif opt_level == 'coverage':
        env.Append(CCFLAGS = ['-g', '-O0', '--coverage'])
        env['TOP'] = '#build/coverage'
        env.Append(LIBS = 'gcov')
    elif opt_level == 'valgrind':
        env.Append(CCFLAGS = ['-g', '-O0', '-DDEBUG'])
        env.Append(LINKFLAGS= ['-g'])
        env['TOP'] = '#build/valgrind'

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

    env.AddMethod(ExtractCppFunc, "ExtractCpp")
    env.AddMethod(ExtractCFunc, "ExtractC")
    env.AddMethod(ExtractHeaderFunc, "ExtractHeader")
    env.AddMethod(ProtocGenDescFunc, "ProtocGenDesc")
    env.AddMethod(ProtocGenCppFunc, "ProtocGenCpp")
    env.AddMethod(SandeshGenOnlyCppFunc, "SandeshGenOnlyCpp")
    env.AddMethod(SandeshGenCppFunc, "SandeshGenCpp")
    env.AddMethod(SandeshGenCFunc, "SandeshGenC")
    env.AddMethod(SandeshGenPyFunc, "SandeshGenPy")
    env.AddMethod(ThriftGenCppFunc, "ThriftGenCpp")
    ThriftSconsEnvPyFunc(env)
    env.AddMethod(ThriftGenPyFunc, "ThriftGenPy")
    CreateIFMapBuilder(env)
    CreateTypeBuilder(env)

    PyTestSuiteCovBuilder = Builder(action = PyTestSuiteCov)
    env.Append(BUILDERS = {'PyTestSuiteCov' : PyTestSuiteCovBuilder})

    # Not used?
    symlink_builder = Builder(action = "cd ${TARGET.dir} && " +
                              "ln -s ${SOURCE.file} ${TARGET.file}")
    env.Append(BUILDERS = {'Symlink': symlink_builder})

    env.AddMethod(UseSystemBoost, "UseSystemBoost")
    env.AddMethod(UseSystemTBB, "UseSystemTBB")
    env.AddMethod(CppDisableExceptions, "CppDisableExceptions")
    env.AddMethod(CppEnableExceptions, "CppEnableExceptions")
    return env
# SetupBuildEnvironment
