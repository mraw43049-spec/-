# migrate_db.py - one-time copy of all data from the OLD Postgres to the NEW one.
# Only READS from the old database. Skips any table that already has rows in the new one.
import os, sys, time, functools
print = functools.partial(print, flush=True)

OLD_URL = os.environ.get("OLD_DATABASE_URL", "").strip()
NEW_URL = os.environ.get("DATABASE_URL", "").strip()
if not OLD_URL or not NEW_URL or OLD_URL == NEW_URL:
    print("ERROR: set OLD_DATABASE_URL (old DB) and DATABASE_URL (new DB), and they must differ.")
    time.sleep(86400); sys.exit(1)

def norm(u):
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    if u.startswith("postgresql://"):
        u = "postgresql+psycopg://" + u[len("postgresql://"):]
    return u

from sqlalchemy import create_engine, text, select, func, inspect
import database, education  # noqa: F401  (loads every table definition; uses DATABASE_URL = NEW)
from database import Base, init_db
new_engine = database.engine
if new_engine.dialect.name != "postgresql":
    print("ERROR: the new DATABASE_URL is not Postgres. Stopping."); time.sleep(86400); sys.exit(1)

old_engine = create_engine(norm(OLD_URL), pool_pre_ping=True)
old_tables = set(inspect(old_engine).get_table_names())
print("Old DB reachable. Tables found:", len(old_tables))

init_db()  # creates empty tables in the NEW database
failed = []
for table in Base.metadata.sorted_tables:
    name = table.name
    if name not in old_tables:
        print(f"- {name}: not in old DB, skipped"); continue
    with new_engine.connect() as c:
        existing = c.execute(select(func.count()).select_from(table)).scalar()
    if existing:
        print(f"- {name}: new DB already has {existing} rows, skipped"); continue
    old_cols = {c["name"] for c in inspect(old_engine).get_columns(name)}
    cols = [c.name for c in table.columns if c.name in old_cols]
    sql = 'SELECT ' + ", ".join(f'"{c}"' for c in cols) + f' FROM "{name}"'
    try:
        copied = 0
        with old_engine.connect() as oc, new_engine.begin() as nc:
            result = oc.execution_options(stream_results=True).execute(text(sql))
            while True:
                chunk = result.fetchmany(1000)
                if not chunk:
                    break
                nc.execute(table.insert(), [dict(r._mapping) for r in chunk])
                copied += len(chunk)
        print(f"- {name}: copied {copied} rows")
    except Exception as e:
        failed.append(name); print(f"- {name}: FAILED -> {e}")

for table in Base.metadata.sorted_tables:  # fix auto-increment counters
    pk = list(table.primary_key.columns)
    try:
        if len(pk) == 1 and pk[0].type.python_type is int:
            col, tbl = pk[0].name, table.name
            with new_engine.begin() as c:
                seq = c.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'"{tbl}"', "c": col}).scalar()
                if seq:
                    c.execute(text(
                        f'SELECT setval(CAST(:s AS regclass), COALESCE((SELECT MAX("{col}") FROM "{tbl}"), 1), '
                        f'(SELECT MAX("{col}") FROM "{tbl}") IS NOT NULL)'), {"s": seq})
    except Exception as e:
        print(f"  (sequence fix skipped for {table.name}: {e})")

print("\n===== CHECK: old vs new row counts =====")
bad = 0
for table in Base.metadata.sorted_tables:
    if table.name not in old_tables:
        continue
    with old_engine.connect() as oc:
        o = oc.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
    with new_engine.connect() as nc:
        n = nc.execute(select(func.count()).select_from(table)).scalar()
    ok = "OK" if o == n else "MISMATCH"
    bad += (o != n)
    print(f"{table.name}: old={o} new={n} {ok}")
print("\nRESULT:", "ALL OK" if not bad and not failed else f"PROBLEMS: mismatches={bad}, failed={failed}")
print("Finished. Change the Start Command back now.")
time.sleep(86400)
