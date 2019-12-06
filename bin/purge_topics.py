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
import concurrent.futures
import sys

from lsst.ts import salobj


SLEEP_TIME = 0.5  # time to sleep after subscribe and before closing the manager


async def main():
    parser = argparse.ArgumentParser(
        description="Purge SAL Command Messages for a CSC component. "
        "This is a workaround for a SAL bug."
        "If no commands, events or telemetry are specified "
        "then all topics are purged"
    )
    parser.add_argument("component", help="Name of SAL component (e.g. ATDome).")
    parser.add_argument(
        "-c", "--commands", nargs="+", default=None, help="Command topics to purge."
    )
    parser.add_argument(
        "-e", "--events", nargs="+", default=None, help="Event topics to purge."
    )
    parser.add_argument(
        "-t", "--telemetry", nargs="+", default=None, help="Telemetry topics to purge."
    )
    args = parser.parse_args()

    await purge_topics(
        component=args.component,
        commands=args.commands,
        events=args.events,
        telemetry=args.telemetry,
    )


def purge_one_topic(component, category, topic_name, sleep):
    """Purge one SAL topic.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    category : `str`
        Type of topic; one of: "command", "event" or "telemetry".
    topic_name : `str`
        Full topic name; the argument to ``func``
    sleep : `float`
        Amount of time to sleep after purging the topic
        before closing the domain (sec).
    """
    TopicClass = dict(
        command=salobj.topics.ControllerCommand,
        event=salobj.topics.RemoteEvent,
        telemetry=salobj.topics.RemoteTelemetry,
    )[category]

    async def doit():
        async with salobj.Domain() as domain:
            try:
                salinfo = salobj.SalInfo(domain=domain, name=component)
                TopicClass(salinfo=salinfo, name=topic_name)
                await asyncio.sleep(sleep)
                print(f"Purged {category} {topic_name}")
            except Exception as e:
                print(f"Could not purge {component} {category} {topic_name}: {e}")
                sys.exit(1)

    asyncio.new_event_loop().run_until_complete(doit())


async def purge_topics(
    component, commands=None, events=None, telemetry=None, sleep=SLEEP_TIME
):
    """Purge commands for a given SAL component.

    Parameters
    ----------
    component : `str`
        Name of SAL component, e.g. "ATDome".
    commands : `list` of `str` (optional)
        Names of comamnds to purge; if None then purge all commands
    sleep : `float`
        Amount of time to sleep after purging each command,
        before closing the SAL object (sec).
    """
    async with salobj.Domain() as domain:
        if commands is None and events is None and telemetry is None:
            salinfo = salobj.SalInfo(domain=domain, name=component)
            commands = salinfo.command_names
            events = salinfo.event_names
            telemetry = salinfo.telemetry_names
        if commands is None:
            commands = ()
        if events is None:
            events = ()
        if telemetry is None:
            telemetry = ()

        loop = asyncio.get_event_loop()
        with concurrent.futures.ProcessPoolExecutor() as pool:
            coros = []
            for topic_name in commands:
                coros.append(
                    loop.run_in_executor(
                        pool, purge_one_topic, component, "command", topic_name, sleep
                    )
                )

            for topic_name in events:
                coros.append(
                    loop.run_in_executor(
                        pool, purge_one_topic, component, "event", topic_name, sleep
                    )
                )

            for topic_name in telemetry:
                coros.append(
                    loop.run_in_executor(
                        pool, purge_one_topic, component, "telemetry", topic_name, sleep
                    )
                )

        await asyncio.gather(*coros)


if __name__ == "__main__":
    asyncio.run(main())
