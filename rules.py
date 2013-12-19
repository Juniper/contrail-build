#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

import os
import re
from SCons.Builder import Builder
from SCons.Script import AddOption, GetOption
import json
import SCons.Util
import subprocess
import sys
import time
import commands

def RunUnitTest(env, target, source, timeout = 60):
    if env['ENV'].has_key('BUILD_ONLY'):
        return
    import subprocess
    test = str(source[0].abspath)
    logfile = open(target[0].abspath, 'w')
    #    env['_venv'] = {target: venv}
    tgt = target[0].name
    if '_venv' in  env and tgt in env['_venv'] and env['_venv'][tgt]:
        cmd = ['/bin/bash', '-c', 'source %s/bin/activate && %s' % (
                env[env['_venv'][tgt]]._path, test)]
    else:
        cmd = [test]
    ShEnv = {env['ENV_SHLIB_PATH']: 'build/lib',
             'HEAPCHECK': 'normal',
             'PPROF_PATH': 'build/bin/pprof',
             'DB_ITERATION_TO_YIELD': '1',
             'PATH': os.environ['PATH']}
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

def TestSuite(env, target, source):
    for test in source:
        log = test[0].abspath + '.log'
        cmd = env.Command(log, test, RunUnitTest)
        env.AlwaysBuild(cmd)
        env.Alias(target, cmd)
    return target

def setup_venv(env, target, venv_name, path=None):
    p = path or env.Dir(env['TOP']).abspath
    shell_cmd = ' && '.join ([
        'cd %s' % p,
        '[ -f ez_setup-0.9.tar.gz ] || curl -o ez_setup-0.9.tar.gz https://pypi.python.org/packages/source/e/ez_setup/ez_setup-0.9.tar.gz',
        '[ -f Python-2.7.tar.bz2 ] || curl -o Python-2.7.tar.bz2 http://www.python.org/ftp/python/2.7/Python-2.7.tar.bz2',
        '[ -d Python-2.7 ] || tar xjvf Python-2.7.tar.bz2',
        '[ -d python2.7 ] || ( cd Python-2.7 && ./configure --prefix=%s/python2.7 && make install ) && ( cd ez_setup-0.9 && ../python2.7/bin/python setup.py install)' % p,
        '[ -f virtualenv-1.10.1.tar.gz ] || curl -o virtualenv-1.10.1.tar.gz https://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.10.1.tar.gz',
        '[ -d virtualenv-1.10.1 ] || tar xzvf virtualenv-1.10.1.tar.gz',
        'python2.7/bin/python virtualenv-1.10.1/virtualenv.py --python=python2.7/bin/python %s',
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

    cmd = env.Command(targets, None, 'source %s/bin/activate; pip install %s' %
                      (venv._path, ' '.join(pkg_list)))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def venv_add_build_pkg(env, v, pkg):
    cmd = []
    venv = env[v[0]]
    for p in pkg:
        t = 'build-' + os.path.basename (p)
        cmd += env.Command (t, '',
       'source %s/bin/activate; pushd %s && python setup.py install; popd' % (
              venv._path, p))
    env.AlwaysBuild(cmd)
    env.Depends(cmd, venv)
    return cmd

def PyTestSuite(env, target, source, venv=None):
    for test in source:
        log = test + '.log'
        cmd = env.Command(log, test, RunUnitTest)
        env.AlwaysBuild(cmd)
        env.Alias(target, cmd)
        if venv:
            env.Depends(cmd, venv)
            try:
                env['_venv'][log] = venv[0]
            except KeyError:
                env['_venv'] = {log: venv[0]}
    return target

def UnitTest(env, name, sources):
    test_env = env.Clone()
    if sys.platform != 'darwin' and env.get('OPT') != 'coverage':
        test_env.Append(LIBPATH = '#/build/lib')
        test_env.Append(LIBS = ['tcmalloc'])
    return test_env.Program(name, sources)

def GenerateBuildInfoCode(env, target, source, path):
    if not os.path.isdir(path):
        os.makedirs(path)
    env.Command(target=target, source=source, action=BuildInfoAction, chdir = path)
    return

def BuildInfoAction(env, target, source):
    try:
        build_user = os.environ['USER']
    except KeyError:
        build_user = "unknown"

    try:
        build_host = os.environ['HOSTNAME']
    except KeyError:
        build_host = "unknown"

    # Fetch Time in UTC
    import datetime
    build_time = unicode(datetime.datetime.utcnow())

    # Fetch git version
    p = subprocess.Popen('git log --oneline | head -1 | awk \'{ print $1 }\'',
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell='True')
    build_git_info, err = p.communicate()
    build_git_info = build_git_info.strip()

    # Fetch build version
    file_path = env.Dir('#').abspath + '/controller/src/base/version.info'
    f = open(file_path)
    build_version = (f.readline()).strip()

    # build json string containing build information
    info = {
        'build-version': build_version,
        'build-time': build_time,
        'build-user': build_user,
        'build-hostname': build_host,
        'build-git-ver': build_git_info
    }
    jsdata = json.dumps({'build-info': info})

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

    h_file = file('buildinfo.h', 'w')
    h_file.write(h_code)
    h_file.close()

    cc_file = file('buildinfo.cc', 'w')
    cc_file.write(cc_code)
    cc_file.close()
    return 
#end GenerateBuildInfoCode

def GenerateBuildInfoPyCode(env, target, source, path):
    import os
    import subprocess

    try:
        build_user = os.environ['USER']
    except KeyError:
        build_user = "unknown"

    try:
        build_host = os.environ['HOSTNAME']
    except KeyError:
        build_host = "unknown"

    # Fetch Time in UTC
    import datetime
    build_time = unicode(datetime.datetime.utcnow())

    # Fetch git version
    p = subprocess.Popen('git log --oneline | head -1 | awk \'{ print $1 }\'',
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell='True')
    build_git_info, err = p.communicate()
    build_git_info = build_git_info.strip()

    # Fetch build version
    file_path = env.Dir('#').abspath + '/controller/src/base/version.info'
    f = open(file_path)
    build_version = (f.readline()).strip()

    # build json string containing build information
    build_info = "{\\\"build-info\\\" : [{\\\"build-version\\\" : \\\"" + str(build_version) + "\\\", \\\"build-time\\\" : \\\"" + str(build_time) + "\\\", \\\"build-user\\\" : \\\"" + build_user + "\\\", \\\"build-hostname\\\" : \\\"" + build_host + "\\\", \\\"build-git-ver\\\" : \\\"" + build_git_info + "\\\", "
    py_code ="build_info = \""+ build_info + "\";\n"
    if not os.path.exists(path):
        os.makedirs(path)
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
        if ext == 'cpp':
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


class SandeshWarning(SCons.Warnings.Warning):
    pass

class SandeshCodeGeneratorError(SandeshWarning):
    pass

# SandeshGenOnlyCpp Methods
def SandeshOnlyCppBuilder(target, source, env):
    opath = str(target[0]).rsplit('/',1)[0] + "/"
    sname = str(target[0]).rsplit('/',1)[1].rsplit('_',1)[0]
    sandeshcmd = env.Dir(env['TOP_BIN']).abspath + '/sandesh'
    code = subprocess.call(sandeshcmd + ' --gen cpp -I controller/src/ -out ' + 
                           opath + " " + str(source[0]), shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'Sandesh code generation failed')
    cname = sname + "_html.cpp"
    os.system("echo \"int " + sname + "_marker = 0;\" >> " + opath + cname)

def SandeshSconsEnvOnlyCppFunc(env):
    onlycppbuild = Builder(action = SandeshOnlyCppBuilder)
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
    env.Depends(targets, '#/build/bin/sandesh')
    return env.SandeshOnlyCpp(targets, file)

# SandeshGenCpp Methods
def SandeshCppBuilder(target, source, env):
    opath = str(target[0]).rsplit('/',1)[0] + "/"
    sname = str(target[0]).rsplit('/',1)[1].rsplit('_',1)[0]
    sandeshcmd = env.Dir(env['TOP_BIN']).abspath + '/sandesh'
    code = subprocess.call(sandeshcmd + ' --gen cpp --gen html -I controller/src/ -I tools -out '
                           + opath + " " + str(source[0]), shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError, 
                                     'Sandesh code generation failed')
    tname = sname + "_html_template.cpp"
    hname = sname + ".xml"
    cname = sname + "_html.cpp"
    if not env.Detect('xxd'):
        raise SCons.Errors.StopError(SandeshCodeGeneratorError,
                                     'xxd not detected on system')
    os.system("echo \"namespace {\"" + " >> " + opath + cname)
    os.system("(cd " + opath + " ; xxd -i " + hname + " >> " + cname + " )")
    os.system("echo \"}\"" + " >> " + opath + cname)
    os.system("cat " + opath + tname + " >> " + opath + cname)

def SandeshSconsEnvCppFunc(env):
    cppbuild = Builder(action = SandeshCppBuilder)
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
    env.Depends(targets, '#/build/bin/sandesh')
    return env.SandeshCpp(targets, file)

# SandeshGenC Methods
def SandeshCBuilder(target, source, env):
    opath = str(target[0]).rsplit('gen-c',1)[0]
    sandeshcmd = env.Dir(env['TOP_BIN']).abspath + '/sandesh'
    code = subprocess.call(sandeshcmd + ' --gen c -o ' + opath +
                           ' ' + str(source[0]), shell=True) 
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError, 
                                     'Sandesh code generation failed')
            
def SandeshSconsEnvCFunc(env):
    cbuild = Builder(action = SandeshCBuilder)
    env.Append(BUILDERS = {'SandeshC' : cbuild})

def SandeshGenCFunc(env, file):
    SandeshSconsEnvCFunc(env)
    suffixes = ['_types.h', '_types.c']
    basename = Basename(file)
    targets = map(lambda suffix: 'gen-c/' + basename + suffix, suffixes)
    env.Depends(targets, '#/build/bin/sandesh')
    return env.SandeshC(targets, file)

# SandeshGenPy Methods
def SandeshPyBuilder(target, source, env):
    opath = str(target[0]).rsplit('/',1)[0] 
    py_opath = opath.rsplit('/',1)[0] + '/'
    sandeshcmd = env.Dir(env['TOP_BIN']).abspath + '/sandesh'
    code = subprocess.call(sandeshcmd + ' --gen py:new_style -I controller/src/ -I tools -out ' + \
        py_opath + " " + str(source[0]), shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError, 
                                     'Sandesh Compiler Failed')
    html_opath = opath + '/'
    code = subprocess.call(sandeshcmd + ' --gen html -I controller/src/ -I tools -out ' + \
        html_opath + " " + str(source[0]), shell=True)
    if code != 0:
        raise SCons.Errors.StopError(SandeshCodeGeneratorError, 
                                     'Sandesh code generation failed')

def SandeshSconsEnvPyFunc(env):
    pybuild = Builder(action = SandeshPyBuilder)
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

    env.Depends(targets, '#/build/bin/sandesh')
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
            exit(1)
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
        RunUnitTest(env, [env.File(logfile)], [env.File(test)], 300)
    return None

def PlatformDarwin(env):
    ver = subprocess.check_output("sw_vers | \grep ProductVersion", shell=True).rstrip('\n')
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

def SetupBuildEnvironment(conf):
    AddOption('--optimization', dest = 'opt',
              action='store', default='debug',
              choices = ['debug', 'production', 'coverage', 'profile'],
              help='optimization level: [debug|production|coverage|profile]')

    AddOption('--target', dest = 'target',
              action='store',
              choices = ['i686', 'x86_64'])

    env = CheckBuildConfiguration(conf)

    env['OPT'] = GetOption('opt')
    env['TARGET_MACHINE'] = GetOption('target')

    if sys.platform == 'darwin':
        PlatformDarwin(env)
        env['ENV_SHLIB_PATH'] = 'DYLD_LIBRARY_PATH'
    else:
        env['ENV_SHLIB_PATH'] = 'LD_LIBRARY_PATH'

    if env.get('TARGET_MACHINE') == 'i686':
        env.Append(CCFLAGS = '-march=' + arch)

    env['TOP_BIN'] = '#build/bin'
    env['TOP_INCLUDE'] = '#build/include'
    env['TOP_LIB'] = '#build/lib'

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

    env.Append(BUILDERS = {'PyTestSuite': PyTestSuite })
    env.Append(BUILDERS = {'TestSuite': TestSuite })
    env.Append(BUILDERS = {'UnitTest': UnitTest})
    env.Append(BUILDERS = {'GenerateBuildInfoCode': GenerateBuildInfoCode})
    env.Append(BUILDERS = {'GenerateBuildInfoPyCode': GenerateBuildInfoPyCode})

    env.Append(BUILDERS = {'setup_venv': setup_venv})
    env.Append(BUILDERS = {'venv_add_pip_pkg': venv_add_pip_pkg })
    env.Append(BUILDERS = {'venv_add_build_pkg': venv_add_build_pkg })

    env.AddMethod(ExtractCppFunc, "ExtractCpp")
    env.AddMethod(ExtractCFunc, "ExtractC")
    env.AddMethod(ExtractHeaderFunc, "ExtractHeader")    
    env.AddMethod(SandeshGenOnlyCppFunc, "SandeshGenOnlyCpp")
    env.AddMethod(SandeshGenCppFunc, "SandeshGenCpp")
    env.AddMethod(SandeshGenCFunc, "SandeshGenC")
    env.AddMethod(SandeshGenPyFunc, "SandeshGenPy")
    env.AddMethod(ThriftGenCppFunc, "ThriftGenCpp")
    CreateIFMapBuilder(env)
    CreateTypeBuilder(env)

    PyTestSuiteCovBuilder = Builder(action = PyTestSuiteCov)
    env.Append(BUILDERS = {'PyTestSuiteCov' : PyTestSuiteCovBuilder})

    return env
# SetupBuildEnvironment
