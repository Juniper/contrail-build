#!/usr/bin/env python
#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#
""" Run C++ based unit tests and generate code coverage report using gcov."""

from __future__ import print_function
from distutils.spawn import find_executable
import os
import re
import shutil

def generate_report():
    """ Run the tests and generate report."""
    if os.path.isdir("build/coverage"):
        shutil.rmtree("build/coverage")
    commands = '''
scons -uij32 --optimization=coverage controller/cplusplus_test
lcov --base-directory build/coverage --directory build/coverage -c -o build/coverage/controller_test.info
genhtml -o build/coverage/controller/test_coverage -t test --num-spaces 4 build/coverage/controller_test.info
'''
    for cmd in commands.splitlines():
        cmd_args = cmd.split()
        if (len(cmd_args) == 0):
            continue
        cmd = cmd_args[0]
        cmd_path = find_executable(cmd)
        if not cmd_path:
            continue
        pid = os.fork()
        if pid == 0:
            # Avoid stdout buffering by execing command into child process.
            os.execv(cmd_path, cmd_args)
        os.waitpid(pid, 0)

def fix_report(report):
    """ Remove reports of generated code, test code and third-party code."""
    if not os.path.isfile(report):
        print("Error! Coverage report file %s not found!" % report)
        return

    shutil.move(report, report + ".orig")
    exclude_list = [
        r"boost",
        r"build\/debug\/",
        r"build\/coverage\/",
        r"build\/include\/",
        r"\/test",
        r"usr\/",
    ]

    modified_lines = []
    lines = []
    with open(report + ".orig", "r") as filep:
        lines = filep.readlines()
    i = -1
    while True:
        i += 1
        if i >= len(lines):
            break
        exclude = False
        for pattern in exclude_list:
            if re.search(pattern, lines[i]):
                exclude = True
                break
        if exclude:
            del modified_lines[len(modified_lines)-1]
            i += 8
            continue
        modified_lines.append(lines[i])

    with open(report, "w") as filep:
        for line in modified_lines:
            filep.write(line)

def print_help():
    """ Print generated report access information."""
    print("Archive generated report to a web server. e.g.")
    print("rm -rf /cs-shared/contrail_code_coverage/test_coverage")
    print("cp -a build/coverage/controller/test_coverage " +
          "/cs-shared/contrail_code_coverage/")
    print("http://10.84.5.100/cs-shared/contrail_code_coverage/test_coverage")

def main():
    """ Main routine."""
    generate_report()
    fix_report("build/coverage/controller/test_coverage/index.html")
    fix_report("build/coverage/controller/test_coverage/index-sort-l.html")
    fix_report("build/coverage/controller/test_coverage/index-sort-f.html")
    print_help()

main()
