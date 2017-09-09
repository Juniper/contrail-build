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
  .
  + ------ + third_party
```

Please see this [README](http://juniper.github.io/contrail-vnc/README.html) file details on how to build.
