import os
import uuid
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from .database import SessionLocal, init_db
from .models import Admin
from .auth import get_password_hash, verify_password

load_dotenv()

def seed_superadmin(db: Optional[Session] = None) -> Optional[Admin]:
    """
    Seeds or synchronizes the single Superadmin account from environment variables:
      - SUPERADMIN_EMAIL
      - SUPERADMIN_PASSWORD
      - SUPERADMIN_NAME (optional, defaults to 'Super Administrator')
    
    Enforces that at most 1 superadmin record exists in the database.
    """
    superadmin_email = os.getenv("SUPERADMIN_EMAIL")
    superadmin_password = os.getenv("SUPERADMIN_PASSWORD")
    superadmin_name = os.getenv("SUPERADMIN_NAME", "Super Administrator").strip()

    if not superadmin_email or not superadmin_password:
        print("[SEED] SUPERADMIN_EMAIL or SUPERADMIN_PASSWORD not set in environment. Skipping superadmin seeding.")
        return None

    email = superadmin_email.strip().lower()
    close_session_on_exit = False

    if db is None:
        db = SessionLocal()
        close_session_on_exit = True

    try:
        existing_superadmins = db.query(Admin).filter(Admin.is_superadmin == True).all()

        # Enforce max 1 invariant if duplicates somehow exist
        if len(existing_superadmins) > 1:
            print("[SEED] Warning: Multiple superadmin records detected. Enforcing single superadmin constraint.")
            primary = next((a for a in existing_superadmins if a.email.lower() == email), existing_superadmins[0])
            for extra in existing_superadmins:
                if extra.id != primary.id:
                    extra.is_superadmin = False
            db.commit()
            existing_superadmins = [primary]

        if len(existing_superadmins) == 1:
            superadmin = existing_superadmins[0]
            needs_commit = False

            if superadmin.email.lower() != email:
                superadmin.email = email
                needs_commit = True
            if superadmin.full_name != superadmin_name:
                superadmin.full_name = superadmin_name
                needs_commit = True
            if not superadmin.is_verified:
                superadmin.is_verified = True
                needs_commit = True
            if not verify_password(superadmin_password, superadmin.hashed_password):
                superadmin.hashed_password = get_password_hash(superadmin_password)
                needs_commit = True

            if needs_commit:
                db.commit()
                db.refresh(superadmin)
                print(f"[SEED] Superadmin account updated successfully ({email}).")
            else:
                print(f"[SEED] Superadmin account is up to date ({email}).")
            return superadmin

        # No superadmin currently exists
        existing_admin_by_email = db.query(Admin).filter(Admin.email == email).first()
        if existing_admin_by_email:
            existing_admin_by_email.is_superadmin = True
            existing_admin_by_email.is_verified = True
            existing_admin_by_email.full_name = superadmin_name
            existing_admin_by_email.hashed_password = get_password_hash(superadmin_password)
            db.commit()
            db.refresh(existing_admin_by_email)
            print(f"[SEED] Existing admin promoted to Superadmin ({email}).")
            return existing_admin_by_email

        new_superadmin = Admin(
            id=uuid.uuid4(),
            full_name=superadmin_name,
            email=email,
            hashed_password=get_password_hash(superadmin_password),
            is_verified=True,
            is_superadmin=True
        )
        db.add(new_superadmin)
        db.commit()
        db.refresh(new_superadmin)
        print(f"[SEED] Superadmin account created successfully ({email}).")
        return new_superadmin

    finally:
        if close_session_on_exit:
            db.close()


if __name__ == "__main__":
    init_db()
    seed_superadmin()

