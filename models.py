from database import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime


class Users(Base):

    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    firstname = Column(String)
    lastname = Column(String)
    hash_password = Column(String)
    is_active = Column(Boolean, default=True)
    role = Column(String, default='user')                              # admin or user
    area_id = Column(Integer, ForeignKey('areas.id'), nullable=True)   # user's home area


class Areas(Base):

    __tablename__ = 'areas'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    zone = Column(String)
    district = Column(String)
    created_at = Column(DateTime, default=datetime.now)


class LoadSheddingSchedules(Base):

    __tablename__ = 'load_shedding_schedules'

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey('areas.id'))
    title = Column(String, index=True)
    reason = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    status = Column(String, default='scheduled')     # scheduled / ongoing / completed / cancelled
    created_at = Column(DateTime, default=datetime.now)


class Outages(Base):

    __tablename__ = 'outages'

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey('areas.id'))
    reported_by = Column(Integer, ForeignKey('users.id'))
    title = Column(String, index=True)
    description = Column(Text)
    category = Column(String)                        # transformer_fault, line_break, storm, ...
    status = Column(String, default='reported')      # reported / investigating / resolved / rejected
    created_at = Column(DateTime, default=datetime.now)