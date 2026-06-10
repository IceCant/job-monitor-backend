from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal
from app.models.app_setting import AppSetting
from app.services.scraper_service import run_scrape


class SchedulerService:
    JOB_ID = "scheduled_scrape"

    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
        self.refresh_from_db()

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _load_setting(self) -> dict:
        db = SessionLocal()
        try:
            setting = db.query(AppSetting).filter(AppSetting.key == "scrape_schedule").first()
            if setting is None or not isinstance(setting.value, dict):
                return {"enabled": True, "interval_hours": 6}
            return {
                "enabled": bool(setting.value.get("enabled", True)),
                "interval_hours": max(1, int(setting.value.get("interval_hours", 6))),
            }
        finally:
            db.close()

    def _save_setting(self, enabled: bool, interval_hours: int) -> dict:
        db = SessionLocal()
        try:
            setting = db.query(AppSetting).filter(AppSetting.key == "scrape_schedule").first()
            value = {"enabled": enabled, "interval_hours": max(1, int(interval_hours))}
            if setting is None:
                setting = AppSetting(key="scrape_schedule", value=value)
                db.add(setting)
            else:
                setting.value = value
            db.commit()
            return value
        finally:
            db.close()

    def _scrape_all_job(self):
        db = SessionLocal()
        try:
            run_scrape(db, firm=None)
        finally:
            db.close()

    def _apply_schedule(self, enabled: bool, interval_hours: int):
        if self.scheduler.get_job(self.JOB_ID):
            self.scheduler.remove_job(self.JOB_ID)

        if enabled:
            self.scheduler.add_job(
                self._scrape_all_job,
                "interval",
                hours=max(1, int(interval_hours)),
                id=self.JOB_ID,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )

    def refresh_from_db(self) -> dict:
        setting = self._load_setting()
        self._apply_schedule(setting["enabled"], setting["interval_hours"])
        return setting

    def update_schedule(self, enabled: bool, interval_hours: int) -> dict:
        setting = self._save_setting(enabled=enabled, interval_hours=interval_hours)
        self._apply_schedule(setting["enabled"], setting["interval_hours"])
        return setting


scheduler_service = SchedulerService()

