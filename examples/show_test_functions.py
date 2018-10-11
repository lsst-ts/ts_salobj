"""Print all the functions provided by salpy for the Test device
"""
import SALPY_Test
import salobj

salobj.test_utils.set_random_lsst_dds_domain()
salinfo = salobj.SalInfo(SALPY_Test, 1)
print("SALPY_Test contents:")
for item in sorted(dir(SALPY_Test)):
    if item.startswith("__"):
        continue
    if item.startswith("SAL_"):
        print(f"  {item} = {getattr(SALPY_Test, item)}")
    else:
        print(f"  {item}")
print("\nTest manager contents:")
for item in sorted(dir(salinfo.manager)):
    if item.startswith("__"):
        continue
    print(f"  {item}")
