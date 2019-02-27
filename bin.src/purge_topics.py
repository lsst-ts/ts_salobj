#!/usr/bin/env python
# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import argparse
import asyncio
import importlib
import concurrent.futures
import sys
import time

from lsst.ts import salobj


SLEEP_TIME = 0.5  # time to sleep after subscribe and before closing the manager


async def main():
    parser = argparse.ArgumentParser(
        description="Purge SAL Command Messages for a CSC component. "
        "This is a workaround for a SAL bug."
        "If no commands, events or telemetry are specified "
        "then all topics are purged")
    parser.add_argument("component",
                        help="Name of SAL component (e.g. ATDome).")
    parser.add_argument("-i", "--index", default=0,
                        help="Index of SAL component.")
    parser.add_argument("-c", "--commands", nargs="+", default=None,
                        help="Command topics to purge.")
    parser.add_argument("-e", "--events", nargs="+", default=None,
                        help="Event topics to purge.")
    parser.add_argument("-t", "--telemetry", nargs="+", default=None,
                        help="Telemetry topics to purge.")
    args = parser.parse_args()

    await purge_topics(component=args.component,
                       index=int(args.index),
                       commands=args.commands,
                       events=args.events,
                       telemetry=args.telemetry)


def purge_topic(category, item_name, topic_name, func, sleep):
    """Purge one SAL topic.

    Parameters
    ----------
    category : `str`
        Type of topic; one of: "command", "event" or "telemetry".
    item_name : `str`
        Name of command, event or telemetry
    topic_name : `str`
        Full topic name; the argument to ``func``
    func : ``callable``
        Function to call to subscribe to the topic
    sleep : `float`
        Amount of time to sleep after purging the topic,
        before closing the SAL object (sec).
    """
    try:
        func(topic_name)
    except Exception as e:
        print(f"Could not purge {category} {item_name}: {e}")
        sys.exit(1)
    time.sleep(sleep)
    print(f"Purged {category} {item_name}")


def purge_command(component, index, command_name, sleep=SLEEP_TIME):
    """Purge one SAL command topic.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    index : `int`
        Index of SAL component.
    command_name : `str`
        Name of command.
    sleep : `float`
        Amount of time to sleep after purging the topic,
        before closing the SAL object (sec).
    """
    lib = importlib.import_module(f"SALPY_{component}")
    salinfo = salobj.SalInfo(lib, index)
    topic_name = salinfo.name + "_command_" + command_name
    purge_topic(category="command", item_name=command_name,
                topic_name=topic_name, func=salinfo.manager.salProcessor, sleep=sleep)


def purge_event(component, index, event_name, sleep=SLEEP_TIME):
    """Purge one SAL event topic.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    index : `int`
        Index of SAL component.
    event_name : `str`
        Name of event.
    sleep : `float`
        Amount of time to sleep after purging the topic,
        before closing the SAL object (sec).
    """
    lib = importlib.import_module(f"SALPY_{component}")
    salinfo = salobj.SalInfo(lib, index)
    topic_name = salinfo.name + "_logevent_" + event_name
    purge_topic(category="event", item_name=event_name,
                topic_name=topic_name, func=salinfo.manager.salEventSub, sleep=sleep)


def purge_telemetry(component, index, telemetry_name, sleep=SLEEP_TIME):
    """Purge one SAL telemetry topic.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    index : `int`
        Index of SAL component.
    telemetry_name : `str`
        Name of telemetry.
    sleep : `float`
        Amount of time to sleep after purging the topic,
        before closing the SAL object (sec).
    """
    lib = importlib.import_module(f"SALPY_{component}")
    salinfo = salobj.SalInfo(lib, index)
    topic_name = salinfo.name + "_" + telemetry_name
    purge_topic(category="telemetry", item_name=telemetry_name,
                topic_name=topic_name, func=salinfo.manager.salTelemetrySub, sleep=sleep)


async def purge_topics(component, index=0, commands=None, events=None, telemetry=None, sleep=SLEEP_TIME):
    """Purge commands for a given SAL component.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    index : `int`
        Index of SAL component.
    commands : `list` of `str` (optional)
        Names of comamnds to purge; if None then purge all commands
    sleep : `float`
        Amount of time to sleep after purging each command,
        before closing the SAL object (sec).
    """
    lib = importlib.import_module(f"SALPY_{component}")
    if commands is None and events is None and telemetry is None:
        salinfo = salobj.SalInfo(lib, index)
        commands = salinfo.manager.getCommandNames()
        events = salinfo.manager.getEventNames()
        telemetry = salinfo.manager.getTelemetryNames()
    if commands is None:
        commands = ()
    if events is None:
        events = ()
    if telemetry is None:
        telemetry = ()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ProcessPoolExecutor() as pool:
        coros = []
        for command_name in commands:
            coros.append(loop.run_in_executor(pool, purge_command, component, index, command_name, sleep))

        for event_name in events:
            coros.append(loop.run_in_executor(pool, purge_event, component, index, event_name, sleep))

        for telemetry_name in telemetry:
            coros.append(loop.run_in_executor(pool, purge_telemetry, component, index, telemetry_name, sleep))

    await asyncio.gather(*coros)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
