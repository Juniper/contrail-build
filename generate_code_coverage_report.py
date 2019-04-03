#!/usr/bin/env python
#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#
""" Run C++ based unit tests and generate code coverage report using gcov."""

from __future__ import print_function
import os
import re
import sys
from shutil import copyfile
from subprocess import check_output

def run():
    """ Run the tests and generate report."""
    old_stdout = sys.stdout
    sys.stdout = open("code_coverage.log", 'w')
    commands = '''
rm -rf build/coverage
scons -uij32 --optimization=coverage controller/cplusplus_test
lcov --base-directory build/coverage --directory build/coverage -c -o build/coverage/controller_test.info
genhtml -o build/coverage/controller/test_coverage -t "test coverage" --num-spaces 4 build/coverage/controller_test.info
'''
    for cmd in commands.splitlines():
        print(check_output(cmd, shell=True))
    sys.stdout = old_stdout

def fix_report(report):
    """ Remove reports of generated code, test code and third-party code."""
    if not os.path.isfile(report):
        print("Error! Coverage report file %s not found!" % report)
        return

    copyfile(report, report + ".orig")
    exclude_list = [
        r"boost",
        r"build\/debug\/",
        r"build\/coverage\/",
        r"build\/include\/",
        r"\/test",
        r"usr\/",
    ]

    modify = []
    with open(report, "r") as filep:
        lines = filep.readlines()
        filep.close()
        j = -1
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
                j -= 1
                i += 8
                continue
            j += 1
            if j < len(modify):
                modify[j] = lines[i]
            else:
                modify.append(lines[i])

    with open(report, "w") as filep:
        for i in range(j+1):
            filep.write(modify[i])

def print_help():
    """ Print generated report access information."""
    print("Archive generated report to a web server. e.g.")
    print("rm -rf /cs-shared/contrail_code_coverage/test_coverage")
    print("cp -a build/coverage/controller/test_coverage " +
          "/cs-shared/contrail_code_coverage/")
    print("http://10.84.5.100/cs-shared/contrail_code_coverage/test_coverage")

def main():
    """ Main routine."""
    run()
    fix_report("build/coverage/controller/test_coverage/index.html")
    fix_report("build/coverage/controller/test_coverage/index-sort-l.html")
    fix_report("build/coverage/controller/test_coverage/index-sort-f.html")
    print_help()

main()
