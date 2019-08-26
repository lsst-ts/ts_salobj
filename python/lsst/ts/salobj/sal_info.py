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

__all__ = ["SalInfo", "MAX_RESULT_LEN"]

import asyncio
import concurrent
import logging
import os
import re
import time

import dds
# TODO when we upgrade to OpenSplice 6.10, use its ddsutil:
# import ddsutil
from . import ddsutil

from . import base
from .domain import Domain, DDS_READ_QUEUE_LEN

MAX_RESULT_LEN = 256  # max length for result field of an Ack

# The python logger remembers the level for a given named log
# so the log level needs to be initialized every time
INITIAL_LOG_LEVEL = logging.INFO

# default time to wait for historical data (sec)
# override by setting env var $LSST_DDS_HISTORYSYNC
DEFAULT_LSST_DDS_HISTORYSYNC = 60


class SalInfo:
    """DDS information for one SAL component and its DDS partition

    Parameters
    ----------
    domain : `Domain`
        DDS domain participant and quality of service information.
    name : `str`
        SAL component name.
    index : `int` (optional)
        Component index; 0 or None if this component is not indexed.

    Raises
    ------
    RuntimeError
        If environment variable ``LSST_DDS_DOMAIN`` is not defined.
    RuntimeError
        If the IDL file cannot be found for the specified ``name``.
    TypeError
        If ``domain`` is not a `Domain`.
    ValueError
        If ``index`` is nonzero and the component is not indexed.

    Notes
    -----
    Environment variables:

    * ``LSST_DDS_DOMAIN`` (required): the DDS partition name.
      Since this is parsed by SalInfo, different instances of SalInfo
      can communicate with different DDS partitions,
      even though all share the same Domain object.
    * ``LSST_DDS_HISTORYSYNC`` (optional): time limit (sec)
      for waiting for historical (late-joiner) data.

    Call `start` after constructing this `SalInfo` and all `Remote` objects.
    Until `start` is called no data will be read.

    Each `SalInfo` automatically registers itself with the specified ``domain``
    for cleanup using a weak reference to avoid circular dependencies.
    You may safely close a `SalInfo` before closing its domain,
    and this is recommended if you create and destroy many remotes.

    Contents include:

    * A registry of DDS read condition: DDS reader for reading data.
    * A registry of `topics.BaseTopic` instances for cleanup.
    """
    def __init__(self, domain, name, index=0):
        if not isinstance(domain, Domain):
            raise TypeError(f"domain {domain!r} must be an lsst.ts.salobj.Domain")
        self.isopen = True
        self.domain = domain
        self.name = name
        self.index = 0 if index is None else int(index)

        # Create the publisher and subscriber. Both depend on the DDS
        # partition, and so are created here instead of in Domain,
        # where most similar objects are created.
        self.partition_name = os.environ.get("LSST_DDS_DOMAIN")
        if self.partition_name is None:
            raise RuntimeError("Environment variable $LSST_DDS_DOMAIN not defined")

        partition_qos_policy = dds.PartitionQosPolicy([self.partition_name])

        publisher_qos = domain.qos_provider.get_publisher_qos()
        publisher_qos.set_policies([partition_qos_policy])
        self.publisher = domain.participant.create_publisher(publisher_qos)
        """DDS publisher; used to create topic writers. A dds.Publisher.
        """

        subscriber_qos = domain.qos_provider.get_subscriber_qos()
        subscriber_qos.set_policies([partition_qos_policy])
        self.subscriber = domain.participant.create_subscriber(subscriber_qos)
        """DDS subscriber; used to create topic readers. A dds.Subscriber.
        """

        self.start_task = asyncio.Future()
        """A task that is set done when SalInfo.start is done.

        (or to the exception if that fails).
        """

        self.log = logging.getLogger(self.name)
        self.log.setLevel(INITIAL_LOG_LEVEL)

        # dict of private_seqNum: salobj.topics.CommandInfo
        self._running_cmds = dict()
        # dict of dds.ReadCondition: salobj Topic
        self._readers = dict()
        # the first RemoteCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdReader
        # and set its callback to self._ackcmd_callback
        self._ackcmd_reader = None
        # the first ControllerCommand created should set this to
        # an lsst.ts.salobj.topics.AckCmdWriter
        self._ackcmd_writer = None
        # wait_timeout is a failsafe for shutdown; normally all you have to do
        # is call `close` to trigger the guard condition and stop the wait
        self._wait_timeout = dds.DDSDuration(sec=10)
        self._guardcond = dds.GuardCondition()
        self._waitset = dds.WaitSet()
        self._waitset.attach(self._guardcond)
        self._start_called = False
        self._read_loop_task = None

        self.idl_loc = domain.idl_dir / f"sal_revCoded_{self.name}.idl"
        if not self.idl_loc.is_file():
            raise RuntimeError(f"Cannot find IDL file {self.idl_loc} for name={self.name!r}")
        self.parse_idl()
        if self.index != 0 and not self.indexed:
            raise ValueError(f"Index={index!r} must be 0 or None; {name} is not an indexed SAL component")
        ackcmd_revname = self.revnames.get("ackcmd")
        if ackcmd_revname is None:
            raise RuntimeError(f"Could not find {self.name} topic 'ackcmd'")
        self.ackcmd_type = ddsutil.get_dds_classes_from_idl(self.idl_loc, ackcmd_revname)
        domain.add_salinfo(self)

    def _ackcmd_callback(self, data):
        if not self._running_cmds:
            return
        cmd_info = self._running_cmds.get(data.private_seqNum, None)
        if cmd_info is None:
            return
        isdone = cmd_info.add_ackcmd(data)
        if isdone:
            del self._running_cmds[data.private_seqNum]

    @property
    def AckCmdType(self):
        """The class of command acknowledgement.

        It includes these fields, as well as the usual other
        private fields.

        private_seqNum : `int`
            Sequence number of command.
        ack : `int`
            Acknowledgement code; one of the `SalRetCode` ``CMD_``
            constants, such as `SalRetCode.CMD_COMPLETE`.
        error : `int`
            Error code; 0 for no error.
        result : `str`
            Explanatory message, or "" for no message.
        """
        return self.ackcmd_type.topic_data_class

    def makeAckCmd(self, private_seqNum, ack, error=0, result="", truncate_result=False):
        """Make an AckCmdType object from keyword arguments.

        Parameters
        ----------
        private_seqNum : `int`
            Sequence number of command.
        ack : `int`
            Acknowledgement code; one of the ``salobj.SalRetCode.CMD_``
            constants, such as ``salobj.SalRetCode.CMD_COMPLETE``.
        error : `int`
            Error code. Should be 0 unless ``ack`` is
            ``salobj.SalRetCode.CMD_FAILED``
        result : `str`
            More information. This is arbitrary, but limited to
            `MAX_RESULT_LEN` characters.
        truncate_result : `bool`
            What to do if ``result`` is longer than  `MAX_RESULT_LEN`
            characters:

            * If True then silently truncate ``result`` to `MAX_RESULT_LEN`
              characters.
            * If False then raise `ValueError`

        Raises
        ------
        ValueError
            If ``len(result) > `MAX_RESULT_LEN`` and ``truncate_result``
            is false.
        """
        if len(result) > MAX_RESULT_LEN:
            if truncate_result:
                result = result[0:MAX_RESULT_LEN]
            else:
                raise ValueError(f"len(result) > MAX_RESULT_LEN={MAX_RESULT_LEN}; result={result}")
        return self.AckCmdType(private_seqNum=private_seqNum, ack=ack, error=error, result=result)

    def __repr__(self):
        return f"SalBase({self.name}, {self.index})"

    def parse_idl(self):
        """Parse the SAL-generated IDL file.

        Set the following attributes:

        * command_names: a tuple of command names without the ``"command_"``
          prefix
        * event_names: a tuple of event names, without the ``"logevent_"``
          prefix
        * telemetry_names: a tuple of telemetry topic names
        * sal_topic_names: a tuple of SAL topic names, e.g.
          "logevent_summaryState", in alphabetical order
        * revnames: a dict of topic name: name_revision
        """
        struct_pattern = re.compile(r"\s*struct\s+(?P<name_rev>(?P<name>.+)_(?:[a-zA-Z0-9]+)) +{")
        index_pattern = re.compile(rf"\s*long\s+{self.name}ID;")
        command_names = []
        event_names = []
        telemetry_names = []
        sal_topic_names = []
        revnames = {}
        self.indexed = False
        with open(self.idl_loc, "r") as f:
            for line in f:
                struct_match = struct_pattern.match(line)
                if not struct_match:
                    index_match = index_pattern.match(line)
                    if index_match is not None:
                        self.indexed = True
                    continue
                name = struct_match.group("name")
                name_rev = struct_match.group("name_rev")
                revnames[name] = f"{self.name}::{name_rev}"

                if name.startswith("command_"):
                    command_names.append(name[8:])
                elif name.startswith("logevent_"):
                    event_names.append(name[9:])
                elif name != "ackcmd":
                    telemetry_names.append(name)
                sal_topic_names.append(name)
        self.command_names = tuple(command_names)
        self.event_names = tuple(event_names)
        self.telemetry_names = tuple(telemetry_names)
        self.sal_topic_names = tuple(sorted(sal_topic_names))
        self.revnames = revnames

    async def close(self):
        """Shut down and clean up resources. A no-op if already closed."""
        if not self.isopen:
            return
        self.isopen = False
        self._guardcond.trigger()
        if self._read_loop_task is not None:
            self._read_loop_task.cancel()
        while self._readers:
            read_cond, reader = self._readers.popitem()
            await reader.close()
        while self._running_cmds:
            private_seqNum, cmd_info = self._running_cmds.popitem()
            try:
                cmd_info.abort("shutting down")
            except Exception:
                pass
        self.domain.remove_salinfo(self)

    def add_reader(self, topic):
        """Add a ReadTopic so it can be read.

        Parameters
        ----------
        topic : `topics.ReadTopic`
            Reader topic.
        """
        if self._start_called:
            raise RuntimeError(f"Cannot add topics after the start called")
        if topic._read_condition in self._readers:
            raise RuntimeError(f"{topic} already added")
        self._readers[topic._read_condition] = topic
        self._waitset.attach(topic._read_condition)

    async def start(self):
        """Start the read loop.

        Call this after all topics have been added.

        Raises
        ------
        RuntimeError
            If `start` has already been called.
        """
        if self._start_called:
            raise RuntimeError("Start already called")
        self._start_called = True
        try:
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                t0 = time.time()
                isok = await loop.run_in_executor(pool, self._wait_history)
                dt = time.time() - t0
                if not self.isopen:  # shutting down
                    return
                if isok:
                    self.log.info(f"Read historical data in {dt:0.2f} sec")
                else:
                    self.log.warning(f"Could not read historical data in {dt:0.2f} sec")

                # read historical (late-joiner) data
                for read_cond, reader in list(self._readers.items()):
                    if not self.isopen:  # shutting down
                        return
                    if reader.volatile or not reader.isopen:
                        # reader gets no late-joiner data or is closed
                        continue
                    try:
                        data_list = reader._reader.take_cond(read_cond, DDS_READ_QUEUE_LEN)
                    except dds.DDSException as e:
                        self.log.warning(f"dds error while reading late joiner data for {reader}; "
                                         f"trying again: {e}")
                        time.sleep(0.001)
                        try:
                            data_list = reader._reader.take_cond(read_cond, DDS_READ_QUEUE_LEN)
                        except dds.DDSException as e:
                            raise RuntimeError(f"dds error while reading late joiner data for {reader}; "
                                               "giving up") from e
                    self.log.debug(f"Read {len(data_list)} history items for {reader}")
                    sd_list = [self._sample_to_data(sd, si) for sd, si in data_list if si.valid_data]
                    if len(sd_list) < len(data_list):
                        ninvalid = len(data_list) - len(sd_list)
                        self.log.warning(f"Bug: read {ninvalid} late joiner items for {reader}")
                    if reader.max_history > 0:
                        sd_list = sd_list[-reader.max_history:]
                        if sd_list:
                            reader._queue_data(sd_list)
            self._read_loop_task = asyncio.ensure_future(self._read_loop())
            self.start_task.set_result(None)
        except Exception as e:
            self.start_task.set_exception(e)
            raise

    async def _read_loop(self):
        """Read and process data."""
        loop = asyncio.get_event_loop()
        self.domain.num_read_loops += 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                while self.isopen:
                    conditions = await loop.run_in_executor(pool, self._wait_next)
                    if not self.isopen:
                        # shutting down; clean everything up
                        return
                    for condition in conditions:
                        reader = self._readers.get(condition)
                        if reader is None or not reader.isopen:
                            continue
                        # odds are we will only get one value per read,
                        # but read more so we can tell if we are falling behind
                        data_list = reader._reader.take_cond(condition, reader._data_queue.maxlen)
                        if len(data_list) == 1:
                            reader._warned_readloop = False
                        if len(data_list) >= 10 and not reader._warned_readloop:
                            reader._warned_readloop = True
                            self.log.warning(f"{reader!r} falling behind; read {len(data_list)} messages")
                        sd_list = [self._sample_to_data(sd, si) for sd, si in data_list if si.valid_data]
                        if len(sd_list) < len(data_list):
                            ninvalid = len(data_list) - len(sd_list)
                            self.log.warning(f"Bug: read {ninvalid} invalid items for {reader}")
                        if sd_list:
                            reader._queue_data(sd_list)
                        await asyncio.sleep(0)  # free the event loop
        except asyncio.CancelledError:
            raise
        except Exception:
            self.log.exception("_read_loop failed")
        finally:
            self.domain.num_read_loops -= 1

    def _sample_to_data(self, sd, si):
        """Process one sample data, sample info pair.

        Set sd.private_rcvStamp based on si.reception_timestamp
        and return the updated sd.
        """
        rcv_utc = si.reception_timestamp*1e-9
        rcv_tai = base.tai_from_utc(rcv_utc)
        sd.private_rcvStamp = rcv_tai
        return sd

    def _wait_next(self):
        """Wait for data to be available for any read topic.

        Blocks, so intended to be run in a background thread.

        Returns
        -------
        conditions : `List` of ``dds conditions``
            List of one or more dds read conditions and/or the guard condition
            which have been triggered.
        """
        self.domain.num_read_threads += 1
        conditions = self._waitset.wait(self._wait_timeout)
        self.domain.num_read_threads -= 1
        return conditions

    def _wait_history(self):
        """Wait for historical data to be available for all topics.

        Blocks, so intended to be run in a background thread.

        Returns
        -------
        iosk : `bool`
            True if we got historical data or none was wanted
        """
        time_limit = os.environ.get("LSST_DDS_HISTORYSYNC")
        if time_limit is None:
            time_limit = DEFAULT_LSST_DDS_HISTORYSYNC
        else:
            time_limit = float(time_limit)
        wait_timeout = dds.DDSDuration(sec=time_limit)
        num_ok = 0
        num_checked = 0
        t0 = time.time()
        for reader in list(self._readers.values()):
            if not self.isopen:  # shutting down
                return False
            if reader.volatile or not reader.isopen:
                continue
            num_checked += 1
            isok = reader._reader.wait_for_historical_data(wait_timeout)
            if isok:
                num_ok += 1
            elapsed_time = time.time() - t0
            rem_time = max(0.01, time_limit - elapsed_time)
            wait_timeout = dds.DDSDuration(sec=rem_time)
        return num_ok > 0 or num_checked == 0
