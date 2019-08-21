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

__all__ = ["Domain", "DDS_READ_QUEUE_LEN"]

import asyncio
import ipaddress
import os
import random
import weakref
import warnings

import dds

from lsst.ts import idl

# Length of DDS read queue
# I would prefer to set this in the QoS file,
# but dds does not make the information available
DDS_READ_QUEUE_LEN = 100  # length of DDS read queue

MAX_RANDOM_HOST = (1 << 31) - 1


class Domain:
    """dds domain participant and quality of service information.

    Notes
    -----
    Environment variables:

    * LSST_DDS_IP (optional) is used to set the ``host`` attribute.
      If provided, it must be a dotted numeric IP address, e.g. "192.168.0.1".
      The ``host`` attribute is set to the integer equivalent, or a positive
      random integer if the environment variable if not provided.
      This value is used to set the ``private_host`` field of topics
      when writing them.

    It is important to close a `Domain` when you are done with it, especially
    in unit tests, because otherwise unreleased resources may cause problems.
    To make this easier `Domain` is a context manager.

    `Domain` contains a registry of `SalInfo` instances, so that it can close
    them when the domain is closed. The registry uses weak references to avoid
    circular dependencies (since SalInfo stores the domain). `SalInfo`
    instances automatically register themselves with the provided domain.

    To conserve resources you should have only one `Domain` per process.
    Thus:

    * `Controller` creates its own Domain as attribute ``domain``
      and closes it when the controller is closed. To create a
      `Remote` for a controller, use the domain from the controller, e.g.::

        controller = Controller(name="Test", index=47)
        try:
            remote = Remote(domain=controller.domain, name="Test", index=47)
            ...
        finally:
            await controller.close()

        # or if you only want the objects for the duration of a function,
        # e.g in a unit test:
        async with Controller(name="Test", index=47) as controller:
            remote = Remote(domain=controller.domain, name="Test", index=47)
            ...

    * If you are creating `Remote`s without a `Controller` then you must
      create the Domain yourself and close it when you are finished, e.g.::

        domain = salobj.Domain()
        try:
            remote = salobj.Remote(domain=domain, name="Test", index=47)
            ...
        finally:
            await domain.close()

        # or if you only want the objects for the duration of a function,
        # e.g in a unit test:
        async with salobj.Domain() as domain:
            test_remote = salobj.Remote(domain=domain, name="Test", index=5)
    """
    def __init__(self):
        self.participant = None

        # accumulators for verifying that close is working
        self.num_read_loops = 0
        self.num_read_threads = 0

        # set of SalInfo
        self._salinfo_set = weakref.WeakSet()

        host = os.environ.get("LSST_DDS_IP")
        if host is None:
            host = random.randint(1, MAX_RANDOM_HOST)
        else:
            try:
                host = int(ipaddress.IPv4Address(host))
            except ipaddress.AddressValueError as e:
                raise ValueError(f"Could not parse $LSST_DDS_IP={host} "
                                 "as a numeric IP address (e.g. '192.168.0.1')") from e
        self.host = host
        """Value for the private_host field of output samples."""

        self.origin = os.getpid()
        """Value for the private_origin field of output samples."""

        self.idl_dir = idl.get_idl_dir()

        qos_path = idl.get_qos_path()
        self.qos_provider = dds.QosProvider(qos_path.as_uri(), 'DDS DefaultQosProfile')
        """Quality of service provider, a dds.QosProvider"""

        participant_qos = self.qos_provider.get_participant_qos()
        self.participant = dds.DomainParticipant(qos=participant_qos)
        """Domain participant, a dds.DomainParticipant"""

        # Create quality of service objects that do not depend on
        # the DDS partition. The two that do (publisher and subscriber)
        # are created in SalInfo, so that different SalInfo can be used
        # with different partitions.
        try:
            self.topic_qos = self.qos_provider.get_topic_qos()
            """Quality of service for topics, a dds.Qos"""

            self.writer_qos = self.qos_provider.get_writer_qos()
            """Quality of service for topic writers, a dds.Qos"""

            read_queue_policy = dds.HistoryQosPolicy(depth=DDS_READ_QUEUE_LEN,
                                                     kind=dds.DDSHistoryKind.KEEP_LAST)
            self.reader_qos = self.qos_provider.get_reader_qos()
            self.reader_qos.set_policies([read_queue_policy])
            """Quality of service for topic readers, a dds.Qos"""
        except Exception:
            # very unlikely, but just in case...
            self.participant.close()
            raise

    @property
    def salinfo_set(self):
        return self._salinfo_set

    def add_salinfo(self, salinfo):
        """Add the specified salinfo to the internal registry.

        Parameters
        ----------
        salinfo : `SalInfo`
            SAL component information

        Raises
        ------
        RuntimeError
            If the salinfo is already present
        """
        if salinfo in self._salinfo_set:
            raise RuntimeError(f"salinfo {salinfo} already added")
        self._salinfo_set.add(salinfo)

    def remove_salinfo(self, salinfo):
        """Remove the specified salinfo from the internal registry.

        Parameters
        ----------
        salinfo : `SalInfo`
            SAL component information

        Returns
        -------
        removed : `boolean`
            True if removed, False if not found
        """
        try:
            self._salinfo_set.remove(salinfo)
            return True
        except KeyError:
            return False

    async def close(self):
        """Close all registered `SalInfo` and the dds domain participant"""
        if self.participant is None:
            return
        while self._salinfo_set:
            salinfo = self._salinfo_set.pop()
            await salinfo.close()
        self.close_dds()
        # give read loops a bit more time
        await asyncio.sleep(0.01)
        if self.num_read_loops != 0 or self.num_read_threads != 0:
            warnings.warning(f"After Domain.close num_read_loops={self.num_read_loops} and "
                             f"num_read_threads={self.num_read_threads}; both should be 0")

    def close_dds(self):
        """Close the dds DomainParticipant."""
        participant = getattr(self, "participant", None)
        if participant is not None:
            participant.close()
            self.participant = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, type, value, traceback):
        await self.close()

    def __del__(self):
        """Last-ditch effort to clean up critical resources.

        Users should call `close` instead, because it does more,
        and because ``__del__`` is not reliably called.
        """
        self.close_dds()
