import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tcc_research_os.database import Base


@pytest.fixture()
def db(tmp_path):
    database_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{database_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
