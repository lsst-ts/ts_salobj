import asyncio

taskdict = dict()


async def start(id, timelim):
    print(f"start({id}, {timelim})")
    coro = wait_one(id, timelim)
    task = asyncio.ensure_future(coro)
    taskdict[id] = task
    if len(taskdict) == 1:
        asyncio.ensure_future(set_done())
    return await task


async def wait_one(id, timelim):
    print(f"wait_one({id}, {timelim})")
    await asyncio.sleep(timelim)
    print("sleep done")
    if id in taskdict:
        print(f"delete {id}")
        del taskdict[id]
    return None


async def set_done():
    while taskdict:
        print(f"set_done starts; taskdict keys={taskdict.keys()}")
        await asyncio.sleep(1)
        key, task = taskdict.popitem()
        print(f"setting {key} done")
        task.set_result(f"result is key={key}")


async def doit():
    coro1 = start(1, 3)
    coro2 = start(2, 3)
    await asyncio.gather(coro1, coro2)

asyncio.get_event_loop().run_until_complete(doit())
