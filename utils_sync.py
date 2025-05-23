# utils_sync.py
import os
import time
import datetime
import requests
import asyncio
import threading
from typing import List, Dict, Optional
from database import SyncTask, get_session, init_db
from sqlalchemy.orm import Session

# Global variable to track current sync task
current_sync_task_id = None
sync_abort_flag = False


class SyncManager:
    def __init__(self, db_engine):
        self.db_engine = db_engine
        self.event_subscribers = set()
        self.event_loop = None
        self.loop_thread = None
        self._start_event_loop()

    def _start_event_loop(self):
        """Start event loop in separate thread"""

        def run_loop():
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            self.event_loop.run_forever()

        self.loop_thread = threading.Thread(target=run_loop, daemon=True)
        self.loop_thread.start()

        # Wait for loop to be ready
        while self.event_loop is None:
            time.sleep(0.01)

    def add_event_subscriber(self, queue):
        """Add a queue to receive sync events"""
        self.event_subscribers.add(queue)

    def remove_event_subscriber(self, queue):
        """Remove a queue from sync events"""
        self.event_subscribers.discard(queue)

    def broadcast_event(self, event_type: str, data: dict):
        """Broadcast sync event to all subscribers (thread-safe)"""
        if self.event_loop and not self.event_loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._async_broadcast_event(event_type, data), self.event_loop
            )

    async def _async_broadcast_event(self, event_type: str, data: dict):
        """Internal async method for broadcasting events"""
        event_data = {"event": event_type, "data": data}

        # Remove closed queues
        closed_queues = set()
        for queue in self.event_subscribers:
            try:
                await queue.put(event_data)
            except:
                closed_queues.add(queue)

        # Clean up closed queues
        for queue in closed_queues:
            self.event_subscribers.discard(queue)

    def get_active_sync_task(self) -> Optional[SyncTask]:
        """Get currently active sync task"""
        session = get_session(self.db_engine)
        try:
            active_task = (
                session.query(SyncTask)
                .filter(SyncTask.status.in_(["started", "inprogress"]))
                .first()
            )
            return active_task
        finally:
            session.close()

    def create_sync_task(self, total_playlists: int) -> int:
        """Create a new sync task and return its ID"""
        global current_sync_task_id, sync_abort_flag

        # Check if there's already an active sync
        if self.get_active_sync_task():
            raise ValueError("Another sync is already in progress")

        session = get_session(self.db_engine)
        try:
            sync_task = SyncTask(
                status="started", total_playlists=total_playlists, processed_playlists=0
            )
            session.add(sync_task)
            session.commit()
            current_sync_task_id = sync_task.id
            sync_abort_flag = False
            return sync_task.id
        finally:
            session.close()

    def update_sync_task(self, task_id: int, **kwargs):
        """Update sync task with new data"""
        session = get_session(self.db_engine)
        try:
            sync_task = session.query(SyncTask).filter(SyncTask.id == task_id).first()
            if sync_task:
                for key, value in kwargs.items():
                    setattr(sync_task, key, value)

                if kwargs.get("status") in ["completed", "failed", "aborted"]:
                    sync_task.completed_at = datetime.datetime.now()

                session.commit()
        finally:
            session.close()

    def abort_sync_task(self, task_id: int):
        """Abort a sync task"""
        global sync_abort_flag
        sync_abort_flag = True
        self.update_sync_task(task_id, status="aborted")

    def get_all_sync_tasks(self) -> List[SyncTask]:
        """Get all sync tasks ordered by started_at desc"""
        session = get_session(self.db_engine)
        try:
            tasks = session.query(SyncTask).order_by(SyncTask.started_at.desc()).all()
            return tasks
        finally:
            session.close()


def send_playlists_to_api_sync(playlists: List[Dict], sync_manager: SyncManager):
    """Synchronous background task to send playlists to remote API with real-time updates"""
    global current_sync_task_id, sync_abort_flag

    URL = os.environ.get("REMOTE_SERVER_URL")
    if not URL:
        if current_sync_task_id:
            sync_manager.update_sync_task(
                current_sync_task_id,
                status="failed",
                error_message="REMOTE_SERVER_URL not configured",
            )
            sync_manager.broadcast_event(
                "failed",
                {
                    "task_id": current_sync_task_id,
                    "error": "REMOTE_SERVER_URL not configured",
                },
            )
        return

    if not current_sync_task_id:
        print("No sync task ID available")
        return

    try:
        sync_manager.update_sync_task(current_sync_task_id, status="inprogress")
        sync_manager.broadcast_event(
            "inprogress",
            {"task_id": current_sync_task_id, "total": len(playlists), "processed": 0},
        )

        processed_count = 0

        for i, pl in enumerate(playlists):
            if sync_abort_flag:
                sync_manager.update_sync_task(current_sync_task_id, status="aborted")
                sync_manager.broadcast_event(
                    "aborted",
                    {"task_id": current_sync_task_id, "processed": processed_count},
                )
                return

            try:
                response = requests.post(URL, json=pl, timeout=10)
                response.raise_for_status()

                processed_count += 1
                sync_manager.update_sync_task(
                    current_sync_task_id, processed_playlists=processed_count
                )

                sync_manager.broadcast_event(
                    "progress",
                    {
                        "task_id": current_sync_task_id,
                        "total": len(playlists),
                        "processed": processed_count,
                        "current_playlist": pl.get("title", "Unknown"),
                    },
                )

                print(f"Successfully sent playlist: {pl.get('title', 'Unknown')}")
                time.sleep(0.1)

            except requests.RequestException as req_error:
                error_msg = f"Network error while sending playlist '{pl.get('title', 'Unknown')}': {req_error}"
                print(error_msg)

                sync_manager.update_sync_task(
                    current_sync_task_id, status="failed", error_message=error_msg
                )
                sync_manager.broadcast_event(
                    "failed",
                    {
                        "task_id": current_sync_task_id,
                        "error": error_msg,
                        "processed": processed_count,
                    },
                )
                return  # Stop processing on first network error

        sync_manager.update_sync_task(current_sync_task_id, status="completed")
        sync_manager.broadcast_event(
            "completed",
            {
                "task_id": current_sync_task_id,
                "total": len(playlists),
                "processed": processed_count,
            },
        )

    except Exception as e:
        error_msg = str(e)
        print(f"Unexpected error in sync task: {error_msg}")
        sync_manager.update_sync_task(
            current_sync_task_id, status="failed", error_message=error_msg
        )
        sync_manager.broadcast_event(
            "failed", {"task_id": current_sync_task_id, "error": error_msg}
        )
    finally:
        current_sync_task_id = None
        sync_abort_flag = False
