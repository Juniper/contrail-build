contrail-build
==============

Contrail VNC build tools

Collection of [SCons](http://www.scons.org) recipes used to build the Contrail Virtual Network Controller.

The build scripts assume the following directory structure:

```
  + [sandbox root]
  .
  + ------ controller
  .
  + ------ + tools
  .        .
  .        + ------ + build
  .        .
  .        + ------ + generateds
  .        .
  .        + ------ + sandesh
  .
  .
  + ------ + vrouter
```

Prerequistes on RHEL/CentOS/Scientific 6.4:
yum install -y scons git python-lxml wget gcc path make unzip flex bison gcc-c++ openssl-devel autoconf automake vim python-devel python-setuptools

Checking out repos:
mkdir tools
git clone https://github.com/Juniper/contrail-controller.git controller
git clone https://github.com/Juniper/contrail-vrouter.git vrouter
git clone https://github.com/Juniper/contrail-sandesh.git tools/sandesh
git clone https://github.com/Juniper/contrail-generateDS.git tools/generateds
git clone https://github.com/Juniper/contrail-third-party.git third_party
