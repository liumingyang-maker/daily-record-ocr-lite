"""后台任务队列：asyncio.Queue 单 worker，不使用 Celery/Redis。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskQueue:
    """进程内单 worker 任务队列。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task | None = None
        self._running_job_id: str | None = None
        self._handler: Callable[[str], Coroutine] | None = None

    def _ensure_queue(self) -> asyncio.Queue[str]:
        """惰性创建队列（绑定当前事件循环）。"""
        loop = asyncio.get_running_loop()
        if self._queue is None or self._loop is not loop:
            if self._worker_task and not self._worker_task.done():
                raise RuntimeError("任务队列仍绑定到另一个正在运行的事件循环")
            self._queue = asyncio.Queue()
            self._loop = loop
        return self._queue

    def set_handler(self, handler: Callable[[str], Coroutine]) -> None:
        """设置任务处理函数。"""
        self._handler = handler

    async def start(self) -> None:
        """启动后台 worker。"""
        self._ensure_queue()
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
        self._worker_task = None
        self._queue = None
        self._loop = None

    async def submit(self, job_id: str) -> None:
        """提交任务到队列。"""
        q = self._ensure_queue()
        await q.put(job_id)
        logger.info("任务 %s 已加入队列，当前排队: %d", job_id, q.qsize())

    @property
    def pending_count(self) -> int:
        return self._queue.qsize() if self._queue else 0

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
        q = self._ensure_queue()
        while True:
            job_id = await q.get()
            self._running_job_id = job_id
            try:
                if self._handler:
                    await self._handler(job_id)
            except Exception as e:
                logger.exception("后台任务 %s 执行失败: %s", job_id, e)
            finally:
                self._running_job_id = None
                q.task_done()


# 全局单例
_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue


def reset_task_queue() -> None:
    """重置全局队列（测试用）。"""
    global _task_queue
    _task_queue = None
