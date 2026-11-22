"""75분 시간 칸을 채운다. 시작 시각과 칸 수는 학교 시간표에 맞게 바꿔 쓸 것.

사용 예:
    import sqlite3, seed_time_slot as sd
    con = sqlite3.connect("ssuroom.db")
    con.executescript(open("schema.sql", encoding="utf-8").read())   # 테이블 만들기
    sd.seed(con)                                                     # 시간 칸 채우기
"""
import sqlite3


def seed(con, first_start="09:00", periods=8, days=("월", "화", "수", "목", "금"),
         length=75, gap=15, grid_name="75분제"):
    con.execute("INSERT OR IGNORE INTO time_grid(name) VALUES (?)", (grid_name,))
    gid = con.execute("SELECT id FROM time_grid WHERE name=?", (grid_name,)).fetchone()[0]
    h, m = map(int, first_start.split(":"))
    t = h * 60 + m
    for p in range(1, periods + 1):
        s, e = t, t + length
        for d in days:
            con.execute(
                "INSERT OR IGNORE INTO time_slot(grid_id,day,period_no,start_time,end_time,label) "
                "VALUES (?,?,?,?,?,?)",
                (gid, d, p, f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}", f"{p}교시"))
        t = e + gap
    con.commit()
    return gid


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "ssuroom.db"
    con = sqlite3.connect(db)
    print("grid_id =", seed(con))
