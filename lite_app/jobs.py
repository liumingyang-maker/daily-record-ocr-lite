"""后台任务队列：asyncio.Queue 单 worker，不使用 Celery/Redis。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class TaskQueue:
    """进程内单 worker 任务队列。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._running_job_id: str | None = None
        self._handler: Callable[[str], Coroutine] | None = None

    def set_handler(self, handler: Callable[[str], Coroutine]) -> None:
        """设置任务处理函数。"""
        self._handler = handler

    async def start(self) -> None:
        """启动后台 worker。"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("后台任务 worker 已启动")

    async def stop(self) -> None:
        """停止 worker。"""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            logger.info("后台任务 worker 已停止")

    async def submit(self, job_id: str) -> None:
        """提交任务到队列。"""
        await self._queue.put(job_id)
        logger.info("任务 %s 已加入队列，当前排队: %d", job_id, self._queue.qsize())

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def running_job_id(self) -> str | None:
        return self._running_job_id

    def get_status(self) -> dict[str, Any]:
        return {
            "pending": self.pending_count,
            "running_job_id": self._running_job_id,
        }

    async def _worker(self) -> None:
        """单 worker 循环：逐个处理任务。"""
        while True:
            job_id = await self._queue.get()
            self._running_job_id = job_id
            try:
                if self._handler:
                    await self._handler(job_id)
            except Exception as e:
                logger.exception("后台任务 %s 执行失败: %s", job_id, e)
            finally:
                self._running_job_id = None
                self._queue.task_done()


# 全局单例
_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
