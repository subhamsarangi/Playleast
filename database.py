# database.py
import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    create_engine,
    DateTime,
    Index,
    Text,
)
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()


class Playlist(Base):
    __tablename__ = "playlists"
    id = Column(String, primary_key=True)
    title = Column(String)
    channel_name = Column(String)
    video_count = Column(Integer)
    last_updated = Column(DateTime, default=func.now())
    last_analyzed = Column(DateTime, default=func.now())
    url = Column(String)
    videos = relationship(
        "Video", back_populates="playlist", cascade="all, delete-orphan"
    )


class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    playlist_id = Column(String, ForeignKey("playlists.id"))
    title = Column(String)
    channel_name = Column(String)
    upload_date = Column(DateTime)
    duration = Column(Float)  # in minutes
    views = Column(Integer)
    likes = Column(Integer)
    like_percentage = Column(Float)
    url = Column(String)
    is_top = Column(Boolean, default=False)
    position = Column(Integer)
    __table_args__ = (Index("idx_playlist_position", "playlist_id", "position"),)
    playlist = relationship("Playlist", back_populates="videos")


class SyncTask(Base):
    __tablename__ = "sync_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(
        String, default="started"
    )  # started, inprogress, completed, failed, aborted
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)
    total_playlists = Column(Integer, default=0)
    processed_playlists = Column(Integer, default=0)
    error_message = Column(Text)

    __table_args__ = (Index("idx_sync_status", "status"),)


def init_db(db_path="sqlite:///youtube_playlists.db"):
    """Initialize the database and create tables if they don't exist."""
    engine = create_engine(db_path)
    Base.metadata.create_all(engine, checkfirst=True)
    return engine


def get_session(engine):
    """Create a session factory for the given engine."""
    Session = sessionmaker(bind=engine)
    return Session()
