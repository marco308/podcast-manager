"""AppSetting model for persisting app-level configuration."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSetting(Base):
    """Key-value store for app-level settings (e.g. schedule overrides)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)

    def __repr__(self) -> str:
        return f"<AppSetting(id={self.id}, key={self.key}, value={self.value})>"
