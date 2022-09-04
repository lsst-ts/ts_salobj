from __future__ import annotations

# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
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

__all__ = ["Domain", "QosSet"]

import asyncio
import os
import types
import typing
import warnings
import weakref
from collections.abc import Sequence

from lsst.ts import idl
from . import base

# Avoid circular imports by only importing SalInfo when type checking
if typing.TYPE_CHECKING:
    from .sal_info import SalInfo

MAX_RANDOM_HOST = (1 << 31) - 1


class Domain:
    r"""Information common to all SalInfo instances.

    The name comes from DDS; the class originally contained a DDS domain
    participant and associated quality of service information.

    Attributes
    ----------
    origin : `int`
        Process ID. Used to set the ``private_origin`` field of output samples.
    default_identity : `str`
        Default value used for the identity field of `SalInfo`.
        Initalized to ``user_host`` but `Controller`\ 's constructor
        sets it to `SalInfo.user_index` so that all `Remote`\ s
        constructed with the controller's domain will have the
        controller's identity.
        For testing purposes, it is allowed to change this field
        before constructing a `Remote`.
    user_host : `str`
        username@host. This will match ``identity`` unless the latter
        is set to a CSC name.
    idl_dir : `pathlib.Path`
        Root directory of the ``ts_idl`` package.

    Notes
    -----
    Reads the following `Environment Variables
    <https://ts-salobj.lsst.io/configuration.html#environment_variables>`_;
    follow the link for details:

    **Cleanup**

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

    * If you are creating `Remote`\ s without a `Controller` then you must
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

    def __init__(self) -> None:
        self.isopen = True
        self.user_host = base.get_user_host()
        self.default_identity = self.user_host

        # Accumulators for verifying that close is working.
        self.num_read_loops = 0

        self.done_task: asyncio.Future = asyncio.Future()

        # Set of SalInfo.
        self._salinfo_set: weakref.WeakSet[SalInfo] = weakref.WeakSet()

        self.origin = os.getpid()
        self.idl_dir = idl.get_idl_dir()

    @property
    def salinfo_set(self) -> weakref.WeakSet[SalInfo]:
        return self._salinfo_set

    def add_salinfo(self, salinfo: SalInfo) -> None:
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

    def remove_salinfo(self, salinfo: SalInfo) -> bool:
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

    def basic_close(self) -> None:
        """A synchronous and less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        while self._salinfo_set:
            salinfo = self._salinfo_set.pop()
            salinfo.basic_close()

    async def close(self) -> None:
        """Close all registered `SalInfo`.

        May be called multiple times. The first call closes the Domain;
        subsequent calls wait until the Domain is closed.
        """
        if not self.isopen:
            await self.done_task
            return
        self.isopen = False
        while self._salinfo_set:
            salinfo = self._salinfo_set.pop()
            await salinfo.close()
        if self.num_read_loops != 0:
            warnings.warn(
                f"After Domain.close num_read_loops={self.num_read_loops}; it should be 0",
                RuntimeWarning,
            )
        self.done_task.set_result(None)

    async def __aenter__(self) -> Domain:
        return self

    async def __aexit__(
        self,
        type: typing.Type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        await self.close()
