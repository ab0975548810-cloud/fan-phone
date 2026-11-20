"""SQLite state on the isolated service's private volume. Never install on production."""
import hashlib
import secrets
import sqlite3
import time
from contextlib import closing


def hashed(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


class PrivateHandoffs:
    def __init__(self, database, authorize, clock=time.time):
        self.database = database
        self.authorize = authorize
        self.clock = clock
        with closing(sqlite3.connect(database)) as db:
            db.execute("""create table if not exists handoffs (
                code_hash text primary key, subject text not null, snapshot text not null,
                expires integer not null, session_hash text unique, session_expires integer,
                created integer not null)""")

    def issue(self, subject, snapshot):
        if not self.authorize(subject):
            raise PermissionError()
        now = int(self.clock())
        code = secrets.token_urlsafe(32)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('begin immediate')
            recent,pending = db.execute("""select count(*),count(case when expires>? and session_hash is null then 1 end)
                from handoffs where subject=? and created>?""",(now,subject,now-60)).fetchone()
            if recent>=6 or pending>=2:
                raise ValueError('Too many pending requests')
            db.execute('insert into handoffs values (?,?,?,?,null,null,?)',
                       (hashed(code),subject,snapshot,now+45,now))
        return code

    def redeem(self, code, subject):
        if not self.authorize(subject):
            raise PermissionError()
        token=secrets.token_urlsafe(32)
        now=int(self.clock())
        with closing(sqlite3.connect(self.database)) as db, db:
            claimed=db.execute("""update handoffs set session_hash=?, session_expires=?
                where code_hash=? and subject=? and expires>? and session_hash is null""",
                (hashed(token),now+900,hashed(code),subject,now))
            if claimed.rowcount!=1:
                raise PermissionError()
        return token

    def access(self, token, snapshot):
        with closing(sqlite3.connect(self.database)) as db:
            row=db.execute("""select subject from handoffs where session_hash=? and snapshot=? 
                and session_expires>?""",(hashed(token),snapshot,int(self.clock()))).fetchone()
        if not row or not self.authorize(row[0]):
            raise PermissionError()
        return row[0]
