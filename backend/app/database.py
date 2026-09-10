import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .models import Base

load_dotenv()

# This pulls from the .env variables we set up earlier
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    # 1. Ensure the pgvector extension is enabled in Postgres
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    
    # 2. Create all tables defined in models.py
    Base.metadata.create_all(bind=engine)

    # 3. Ensure the single superadmin partial unique index exists
    with engine.connect() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_single_superadmin ON admins (is_superadmin) WHERE is_superadmin = true"))
        conn.execute(text("ALTER TABLE students ADD COLUMN IF NOT EXISTS student_book_photo_path VARCHAR"))
        conn.execute(text("ALTER TABLE exam_registrations ADD COLUMN IF NOT EXISTS is_admitted BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE exam_registrations ADD COLUMN IF NOT EXISTS admitted_at TIMESTAMP WITH TIME ZONE"))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()