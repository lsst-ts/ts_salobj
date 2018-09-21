"""Make a Controller and Remote for the Test device
"""
import SALPY_Test
import salobj

salinfo = salobj.utils.SalInfo(SALPY_Test, "Test:1")
command_names = salobj.utils.get_command_names(salinfo.manager)
event_names = salobj.utils.get_event_names(salinfo.manager)
telemetry_names = salobj.utils.get_telemetry_names(salinfo.manager)
print(f"commands for {salinfo.name}:")
for item in command_names:
    print(f"  {item}")
print(f"\nevents for {salinfo.name}:")
for item in event_names:
    print(f"  {item}")
print(f"\ntelemetry topics for {salinfo.name}:")
for item in telemetry_names:
    print(f"  {item}")

print("\nmake remote")
remote = salobj.Remote(SALPY_Test, "Test:1")
print("make controller")
controller = salobj.Controller(SALPY_Test, "Test:1")

print(f"\ndata fields for arrays")
print([item for item in dir(remote.cmd_setArrays.DataType()) if not item.startswith("__")])

print(f"\ndata fields for scalars")
print([item for item in dir(remote.cmd_setScalars.DataType()) if not item.startswith("__")])
