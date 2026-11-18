# PlatformIO pre-script: strip build-machine paths from __FILE__ strings (assert/log messages) so the shipped
# firmware does not contain the developer's user name or folder names.
import os
Import("env")  # noqa: F821
# GCC uses the LAST matching map, so the broad prefix goes first and the specific ones after it
dirs = {
    os.environ.get("TEMP", ""): "tmp",
    env.subst("$PROJECT_DIR"): "fw",             # noqa: F821
    env.subst("$PROJECT_PACKAGES_DIR"): "pkg",   # noqa: F821
    env.subst("$PROJECT_LIBDEPS_DIR"): "lib",    # noqa: F821
}
flags = []
for d, short in dirs.items():
    if not d:
        continue
    for v in {d, d.replace("\\", "/")}:
        flags.append(f"-fmacro-prefix-map={v}={short}")
env.Append(CCFLAGS=flags)  # noqa: F821
