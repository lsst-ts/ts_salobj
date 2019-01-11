#!/usr/bin/env python
"""Print attributes provided the specified SALPY library
"""
import argparse
import importlib

from lsst.ts import salobj

parser = argparse.ArgumentParser()
parser.add_argument("component", help="Name of SAL component, e.g. Scheduler")
args = parser.parse_args()

library_name = f"SALPY_{args.component}"
salobj.test_utils.set_random_lsst_dds_domain()
sallib = importlib.import_module(library_name)

salinfo = salobj.SalInfo(sallib, 0)
print(f"{library_name} contents:")
for item in sorted(dir(sallib)):
    if item.startswith("__"):
        continue
    if item.startswith("SAL_"):
        print(f"  {item} = {getattr(sallib, item)}")
    else:
        print(f"  {item}")
print(f"\n{args.component} manager contents:")
for item in sorted(dir(salinfo.manager)):
    if item.startswith("__"):
        continue
    print(f"  {item}")
