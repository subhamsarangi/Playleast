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
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker


Base = declarative_base()


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(String, primary_key=True)
    title = Column(String)
    channel_name = Column(String)
    video_count = Column(Integer)
    last_updated = Column(DateTime, default=datetime.datetime.now)
    last_analyzed = Column(DateTime, default=datetime.datetime.now)
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


def init_db(db_path="sqlite:///youtube_playlists.db"):
    """Initialize the database and create tables if they don't exist."""
    engine = create_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """Create a session factory for the given engine."""
    Session = sessionmaker(bind=engine)
    return Session()
