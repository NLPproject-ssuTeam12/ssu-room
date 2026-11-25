from test_solver2 import *
c = build(); modes = add_pairs(c); sp = add_section_profs(c)
r = sc.solve(c, 1, 1, time_limit=60); tt = r['timetable_id']
print("1차:", r['status'], "못놓음", len(r['unplaced'])); verify(c, tt)
lab = lambda s: c.execute('select day||period_no from time_slot where id=?',(s,)).fetchone()[0]
day_of = lambda s: c.execute('select day from time_slot where id=?',(s,)).fetchone()[0]
rng = lambda s: tuple(c.execute('select start_time,end_time from time_slot where id=?',(s,)).fetchone())

def apply_alt(c, tt, cid, sec_no, alt):
    c.execute("INSERT INTO timetable(term_id,round_id,kind,parent_id) VALUES (1,1,'TA_EDIT',?)",(tt,)); t2=c.execute("select last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO timetable_section(timetable_id,course_id,section_no,planned_enrollment) SELECT ?,course_id,section_no,planned_enrollment FROM timetable_section WHERE timetable_id=?",(t2,tt))
    moved = {(k[0],k[1],k[2]) for k,_,_ in alt['moves']}
    ks_old = {(a,b,cc):n for a,b,cc,n in c.execute("select course_id,section_no,session_no,count(*) from assignment where timetable_id=? group by 1,2,3",(tt,))}
    secs = [sec_no] if sec_no else [s for s, in c.execute("select distinct section_no from assignment where timetable_id=? and course_id=?",(tt,cid))]
    for a,b,cc,sl,rm in c.execute("select course_id,section_no,session_no,slot_id,room_id from assignment where timetable_id=?",(tt,)).fetchall():
        if a==cid and b in secs: continue
        if (a,b,cc) in moved: continue
        c.execute("INSERT INTO assignment VALUES (?,?,?,?,?,?)",(t2,a,b,cc,sl,rm))
    def put(a,b,cc,start,room,k):
        day,per = c.execute("select day,period_no from time_slot where id=?",(start,)).fetchone()
        for sid, in c.execute("select id from time_slot where day=? and period_no>=? and period_no<?+? order by period_no",(day,per,per,k)):
            c.execute("INSERT INTO assignment VALUES (?,?,?,?,?,?)",(t2,a,b,cc,sid,room))
    for (sec,ss),(start,room) in alt['placements'].items(): put(cid,sec,ss,start,room,alt['ks'][(sec,ss)])
    for k,old,new in alt['moves']: put(k[0],k[1],k[2],new[0],new[1],ks_old[k])
    return t2

# ---- 분반 단위 대안: 분반 교수가 다른 과목의 2분반만
cid = next(iter(sp)); 
print(f"\n[분반 단위 대안] 과목{cid} 2분반 (교수 {sp[cid]}) 현재:", {k[1:]:lab(v[0]) for k,v in sc.load_assignment(c,tt)[0].items() if k[0]==cid and k[1]==2})
alts = sc.alternatives(c,1,1,tt,cid,section_no=2,n=3,time_limit=10)
print(" 대안", len(alts), "개")
for a in alts:
    print("  ", a['stage'], {k:lab(v[0]) for k,v in a['placements'].items()}, "칸수", a['ks'], "이동", len(a['moves']))
    assert all(k[0]==2 for k in a['placements']), "다른 분반이 섞임"
    assert {k:v[0] for k,v in a['placements'].items()} != {k[1:]:v[0] for k,v in sc.load_assignment(c,tt)[0].items() if k[0]==cid and k[1]==2}, "현재 배정과 같음"
    verify(c, apply_alt(c, tt, cid, 2, a), " 적용")

# ---- 조율 쪽 조건
tgt = next(k[0] for k in sc.load_assignment(c,tt)[0] if k[0] not in modes and k[0] not in sp)
print("\n[조율 조건] 대상 과목", tgt, "현재:", {k[1:]:lab(v[0]) for k,v in sc.load_assignment(c,tt)[0].items() if k[0]==tgt})
tests = {
 "월·수 오후(13:30~17:45)": dict(days=[0,2], window=["13:30","17:45"], end_before=[]),
 "수요일은 17:00 전에 끝": dict(days=[], window=None, end_before=[{"day":2,"time":"17:00"}]),
 "화요일이 들어간 안": dict(days=[1], window=None, end_before=[]),
 "칸 번호 목록(월·목만)": dict(slot_ids=[s for s, in c.execute("select id from time_slot where day in ('월','목')")]),
}
for name, cond in tests.items():
    a2 = sc.make_alternatives(c,1,1,tt,tgt,condition=cond,n=3,time_limit=10)
    ok = True
    for a in a2:
        sl = []
        for (sec,ss),(start,room) in a['placements'].items():
            k = a['ks'][(sec,ss)]
            day,per = c.execute("select day,period_no from time_slot where id=?",(start,)).fetchone()
            ids = [r[0] for r in c.execute("select id from time_slot where day=? and period_no>=? and period_no<?+? order by period_no",(day,per,per,k))]
            sl.append((day, rng(ids[0])[0], rng(ids[-1])[1]))
        if cond.get("days") and len(cond["days"])>=2: ok &= all(d in {'월','수'} for d,_,_ in sl)
        if cond.get("days") and len(cond["days"])==1: ok &= any(d=='화' for d,_,_ in sl)
        if cond.get("window"): ok &= all(s_>="13:30" and e_<="17:45" for _,s_,e_ in sl)
        for e in cond.get("end_before",[]): ok &= all(e_<=e["time"] for d,_,e_ in sl if d=='수')
        if cond.get("slot_ids"): ok &= all(d in ('월','목') for d,_,_ in sl)
        print("   ", sl)
    print(f" {name}: 대안 {len(a2)}개, 조건 {'만족' if ok else '위반!'}")

# ---- 제안 저장(분반 번호 포함)
pid = sc.save_proposal(c,1,tt,cid,alts,"시험",section_no=2)
print("\nproposal:", c.execute("select id, course_id, section_no from proposal where id=?",(pid,)).fetchone(),
      "옵션", c.execute("select count(*) from proposal_option where proposal_id=?",(pid,)).fetchone()[0],
      "칸", c.execute("select count(*) from proposal_option_slot s join proposal_option o on o.id=s.option_id where o.proposal_id=?",(pid,)).fetchone()[0])
# ---- 일부만 재풀이: 한 교수 불가 시간 추가
prof = c.execute("select professor_id from course_response limit 1").fetchone()[0]
mine = {(a,b) for a,b in c.execute("select course_id, section_no from v_schedule where timetable_id=? and professor_id=? group by 1,2",(tt,prof))}
old = snapshot(c, tt)
cidp = next(iter(mine))[0]
rid = c.execute("select id from course_response where course_id=? and professor_id=?",(cidp,prof)).fetchone()
if rid:
    s0 = [v for k,v in old.items() if k[0]==cidp][0][0]
    c.execute("INSERT OR REPLACE INTO response_slot VALUES (?,?,?)",(rid[0],s0,'BLOCK')); c.commit()
    for label, kw in [("전체 재풀이", dict(previous_timetable_id=tt)), ("그 교수 분반만 재풀이", dict(previous_timetable_id=tt, free_courses=mine))]:
        t=time.time(); r2 = sc.solve(c,1,1,time_limit=20,**kw); new=snapshot(c,r2['timetable_id'])
        ch = sum(1 for k in old if new.get(k)!=old[k]); out_ = sum(1 for k in old if (k[0],k[1]) not in mine and new.get(k)!=old[k])
        print(f"{label}: 바뀐 세션 {ch}/{len(old)}, 그 교수 분반 밖 {out_}, 못놓음 {len(r2['unplaced'])} {r2['status']} {time.time()-t:.1f}s")
        verify(c, r2['timetable_id'], " 재풀이")
