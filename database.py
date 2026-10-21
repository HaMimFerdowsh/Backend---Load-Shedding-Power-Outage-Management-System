import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

SQLALCHEMY_DATABASE_URL = os.getenv('DATABASE_URL')

if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError('DATABASE_URL environment variable is not set')

if SQLALCHEMY_DATABASE_URL.startswith('postgres://'):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(SQLALCHEMY_DATABASE_URL, poolclass=NullPool)

SessionLocal = sessionmaker(autoflush=False, bind=engine)

Base = declarative_base()