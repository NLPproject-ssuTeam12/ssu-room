// 시연용 가짜 서버. v4 시안(docs/prototype/SSU_room_시연_v4.html)의 로직을 그대로 옮겼다.
// 2단계에서 이 파일은 서버 호출(api/client.ts)로 바뀌고 지워진다. 화면 컴포넌트는 S를 읽고 아래 함수만 부른다.
import { notify } from '../store'
import { toast } from '../ui'
// ---------------- 기본 값 ----------------
const SLOTS=['09:00','10:30','12:00','13:30','15:00','16:30','18:00','19:30'];   // 75분 수업 (API 명세와 같은 8교시)
const DAYN='월화수목금';
const D5=[0,1,2,3,4];
// 주 2회 수업: 월~금 중 두 요일을 자유롭게 묶고, 두 번 다 같은 시각에 75분씩 (키 '02' = 월·수, '14' = 화·금)
/** @type {any} */
const PAT={};for(let a=0;a<5;a++)for(let b=a+1;b<5;b++)PAT[`${a}${b}`]={days:[a,b],label:DAYN[a]+'·'+DAYN[b]};
const PKEYS=Object.keys(PAT);
const patOf=(a,b)=>a<b?`${a}${b}`:`${b}${a}`;
const CHAPEL={day:3,slot:2};   // 1학년 채플 (목 12:00, 가정)
const GEN={days:[1,3],slot:2};   // 교양필수 (화·목 12:00, 가상 규칙): 모든 학년 전공을 두지 않는다
const isGenCell=(d,s)=>GEN.days.includes(d)&&s===GEN.slot;
const EARLY_END_MIN=15;   // 고른 안이 이만큼 이내로만 넘기면 종료 조건으로 넣지 않는다 (API 명세)
const PARTNER={0:2,2:0,1:3,3:1};   // 묶어 칠하기 짝: 월↔수, 화↔목
const toMin=t=>{const [h,m]=t.split(':').map(Number);return h*60+m};
const toHM=v=>`${String(Math.floor(v/60)).padStart(2,'0')}:${String(v%60).padStart(2,'0')}`;
const ROOMS=[ // 순서 = 일반 강의는 문화관부터, 실습실은 305부터
  {id:'문화관 201',bldg:'문화관',lab:false,cap:60},{id:'미래관 410',bldg:'미래관',lab:false,cap:60},{id:'정보관 210',bldg:'정보관',lab:false,cap:45},
  {id:'정보관 305',bldg:'정보관',lab:true,cap:50},{id:'정보관 306',bldg:'정보관',lab:true,cap:50}];   // cap = 정원 (가상)
const BLDGS=['문화관','미래관','정보관'];
const PRIO=['실습실 필요','연구실 위치','집 위치','임용 날짜'];
const RULES=['교수 겹침','강의실 겹침','같은 학년 전공필수 겹침','실습실이 필요하면 실습실로','강의실 정원 ≥ 인원','교수가 불가로 칠한 시간','1학년 채플 시간(목 12:00, 가정) 비우기','교양필수 시간(화·목 12:00, 가상 규칙) 비우기','단과대 건물(문화관·미래관·정보관)'];
const MARKS=['희망','불가'];
const CYC=[null,'희망','불가'];   // 칸을 누를 때마다 이 순서로 바뀜
const MCLS={꼭:'m-must',희망:'m-want',불가:'m-no'};
const mcls=m=>m?MCLS[m]||'':'';
/** @type {any} */
const CONSN={any:'상관없음',want:'연강 선호',avoid:'연강 피함'};
/** 같은 교수가 한 과목의 분반 둘 이상을 맡을 때 분반끼리 놓는 방식 (11/24 회의) */
/** @type {Record<string,string>} */
const SECMODE={any:'상관없음',consec:'분반 연강',cross:'분반 교차'};
/** @type {Record<string,string>} */
const SECMODE_TIP={any:'',consec:'두 분반을 같은 날 이어서 (가→나, 가→나)',cross:'두 분반을 이어서 하되 날마다 순서를 바꿈 (가→나, 나→가)'};
const MAX_SECTIONS=6;   // 조교가 과목마다 여는 분반 수 상한
const R=(a,b)=>Array.from({length:b-a+1},(_,i)=>a+i);
const SIZES=R(6,12).map(i=>i*5);   // 인원: 30~60명, 5명 단위
// 칠하기 값 만들기: [[요일들, 교시들, 표시], ...] 뒤에 오는 것이 앞의 것을 덮는다
function P(spec){const p={};for(const [ds,ss,m] of spec)for(const d of ds)for(const s of ss)p[d+'-'+s]=m;return p}
const F=(spec,o={})=>({paint:P(spec),lab:false,size:null,pref:null,must:false,etc:'',etcOk:false,...o});
const emptyF=()=>F([]);

// 가상 데이터: 12개 분반 + 아무도 안 고른 1개. f = 교수님이 선택칸으로 낸 희망 (솔버가 그대로 읽는 값)
// 요일 0~4 = 월~금, 교시 0~7 = 09:00 10:30 12:00 13:30 15:00 16:30 18:00 19:30. 대부분 칸은 비워 둔다 (안 칠함 = 가능)
const COURSES0=[
 {id:'c1',name:'자료구조',sec:'01',prof:'가',year:2,req:true,f:F([[[0,2],[4],'희망']],{lab:true,pref:'정보관'})},
 {id:'c2',name:'객체지향프로그래밍',sec:'02',prof:'나',year:2,req:true,
  f:F([[[0,2],[0,1],'불가'],[[0,2],[4],'희망']],{lab:true,pref:'정보관',etc:'실습 조교 1명 배정을 부탁드립니다.'})},
 {id:'c3',name:'자연언어처리',sec:'01',prof:'다',year:3,req:false,f:F([[[1,3],[0,1],'희망']])},
 {id:'c4',name:'운영체제',sec:'01',prof:'라',year:3,req:true,f:F([[[1,3],[0],'불가'],[[1,3],[3,4],'희망']],{pref:'정보관'})},
 {id:'c5',name:'컴퓨터네트워크',sec:'01',prof:'마',year:3,req:false,f:F([[[0,2],[5],'희망']],{pref:'미래관'})},
 {id:'c6',name:'인공지능',sec:'01',prof:'바',year:3,req:false,f:F([[[0,2],[1],'희망'],[[1,3],[0],'희망']])},
 {id:'c7',name:'데이터베이스',sec:'01',prof:'사',year:3,req:true,
  f:F([[[4],[4,5],'불가'],[[1,3],[4],'희망']],{lab:true,pref:'정보관',etc:'외부 강의가 있어 학기 중 두 번 대강이 필요합니다.'})},
 {id:'c8',name:'알고리즘',sec:'01',prof:'다',year:2,req:true,f:F([[[1,3],[3,4],'희망']])},
 {id:'c9',name:'기계학습',sec:'01',prof:'아',year:4,req:false,f:F([[[0,2],[1],'희망']])},
 {id:'c10',name:'컴퓨터구조',sec:'02',prof:'자',year:2,req:true,f:F([[[4],[0],'불가'],[[0,2],[3],'희망']])},
 {id:'c11',name:'소프트웨어공학',sec:'01',prof:'차',year:3,req:true,f:F([[[1,3],[6],'불가'],[[1,3],[4],'희망']],{lab:true,pref:'정보관'})},
 {id:'c12',name:'이산수학',sec:'01',prof:'카',year:1,req:true,f:F([[[0],[0],'불가'],[[0,2],[1],'희망']])},
 {id:'c13',name:'컴퓨터비전',sec:'01',prof:null,year:4,req:false},
];
// 담당 교수는 미리 정해지지 않는다. 위 prof는 그 분반을 고른 교수이고, 아래는 같은 분반을 고른 다른 교수 (담당 겹침 시연)
const EXTRA_CLAIMS=[{cid:'c9',prof:'바',f:F([[[0,2],[3,4],'희망']],{etc:'인공지능 수업과 같은 요일이면 좋겠습니다.'})}];
const CONSEC0={다:'avoid'};
const CAP={c1:50,c2:45,c3:45,c4:60,c5:50,c6:55,c7:40,c8:60,c9:45,c10:60,c11:40,c12:50,c13:40};   // 교수님이 고르는 인원의 기본값 (가상)
const PROFS=['가','나','다','라','마','바','사','아','자','차','카'];
const kindOf=c=>c.year===1&&c.req?'전공기초':c.req?'전공필수':'전공선택';
// 시연용 가상 회신 (차수 → 분반 → 답장)
/** @type {any} */
const SCRIPT={1:{c2:'A나 B 괜찮아요. 수요일은 17시 전에 끝나야 해요.',c11:'셋 다 어렵습니다. 화요일, 목요일 오전이면 됩니다.'},2:{c11:'A로 할게요.'}};
const BOT_EX=['객체지향은 왜 밀렸어?','그 강의 C안으로 옮기면?','화요일 오전 비우면?','정보관 305 공사하면?','다 교수 강의 옮겨줘','알고리즘 화·목 16:30으로','지금 조율 중인 거 뭐 있어?','점심 메뉴 추천해줘'];

// ---------------- 상태 ----------------
const clone=o=>JSON.parse(JSON.stringify(o));
const mkClaim=(cid,prof,f)=>({cid,prof,f:{...f,size:f.size||CAP[cid]||40}});
function init(){
  const src=clone(COURSES0);
  const courses=src.map(({prof,f,...c})=>({...c}));
  const claims=[...src.filter(c=>c.prof).map(c=>mkClaim(c.id,c.prof,c.f)),...clone(EXTRA_CLAIMS).map(x=>mkClaim(x.cid,x.prof,x.f))];
  const s={role:'ta',prof:'나',view:'home',stage:'collect',round:0,courses,claims,pick:{},excl:{},consec:clone(CONSEC0),secMode:{},
    assign:{},status:{},blocker:{},reason:{},why:{},conds:{},moved:{},msgs:[],log:[],lastChanged:[],reveal:true,editing:null,room:'all',
    bot:{turns:[],last:null,pending:null},botOpen:false,botSeen:false,botFocus:false,
    method:'llm',llmFail:false,pair:{},
    ttOpen:false,peek:null,autoReply:true,confirms:[],mineOnly:false};   // method = 회신 해석 방식 (API: keyword | llm), peek = 시간표에 미리 볼 대안 {m,k}
  s.log.push({at:'희망 수집',t:`교수 ${new Set(claims.map(x=>x.prof)).size}명이 개설 분반 ${courses.length}개 중 맡을 분반을 골라 희망 ${claims.length}건을 냈습니다 (가상).`});
  return s;
}
// 담당 정리: 한 명만 고르면 그 교수, 여럿이면 조교가 고른 교수, 아무도 없으면 담당 없음
function sync(){
  for(const c of S.courses){
    const cl=S.claims.filter(x=>x.cid===c.id);
    const pick=S.excl[c.id]?null:(S.pick[c.id]&&cl.find(x=>x.prof===S.pick[c.id]))||(cl.length===1?cl[0]:null);
    c.own=S.excl[c.id]?'excl':pick?'ok':cl.length>1?'dup':'none';
    c.prof=pick?pick.prof:null;c.f=pick?pick.f:null;c.byTA=pick?!!pick.byTA:false;
  }
}
const ACT=()=>S.courses.filter(c=>c.own==='ok');
const claimOf=(cid,prof)=>S.claims.find(x=>x.cid===cid&&x.prof===prof);
const etcTodo=()=>ACT().filter(c=>c.f.etc&&!c.f.etcOk).length;
const todo=()=>S.courses.filter(c=>c.own==='dup'||c.own==='none').length+etcTodo();
/** @type {any} */
export let S=init();sync();
export function reset(){S=init();sync()}
let BLOCK=null;   // AI 도우미의 가정 계산에서만 쓰는 임시 제약
let FAIL=null;

// ---------------- 도우미 ----------------
const C=id=>S.courses.find(c=>c.id===id);
const full=c=>`${c.name} ${c.sec}`;
const ROOM=id=>ROOMS.find(r=>r.id===id);
const mins=i=>{const [h,m]=SLOTS[i].split(':').map(Number);return h*60+m};
const endMin=i=>mins(i)+75;
const endOf=i=>{const t=endMin(i);return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`};
const roomText=(p,rm)=>rm[0]===rm[1]?rm[0]:`${DAYN[PAT[p].days[0]]} ${rm[0]} / ${DAYN[PAT[p].days[1]]} ${rm[1]}`;
const altLabel=a=>`${PAT[a.pat].label} ${SLOTS[a.slot]}~${endOf(a.slot)} · ${roomText(a.pat,a.rooms)}`;
const log=(at,t)=>S.log.push({at,t});
const hr=h=>h<8?h+12:h;
function slotOf(h,m=0){const t=h*60+m;let best=0,bd=1e9;SLOTS.forEach((_,i)=>{const d=Math.abs(mins(i)-t);if(d<bd){bd=d;best=i}});return best}
const stageIdx=()=>({collect:0,draft:1,round:2,review:3,confirm:3,final:4})[S.stage];
const openMsgs=()=>S.msgs.filter(m=>m.round===S.round&&S.stage==='round');
// 조사 고르기 (받침 유무). 숫자는 읽는 소리로 본다
function jong(w){const ch=String(w).trim().slice(-1);const dg={0:21,1:8,2:0,3:16,4:0,5:0,6:1,7:8,8:8,9:0};
  if(ch in dg)return dg[ch];const k=ch.charCodeAt(0)-0xAC00;return k>=0&&k<11172?k%28:0}
const jo=(w,a,b)=>w+(jong(w)?a:b);
const ro=w=>{const j=jong(w);return w+(j&&j!==8?'으로':'로')};

// ---------------- 희망 (선택칸 값을 그대로 읽는다) ----------------
const mk=(f,d,s)=>f.paint[d+'-'+s]||null;
const isWant=m=>m==='꼭'||m==='희망';
const hardOk=(c,p,s)=>!PAT[p].days.some(d=>mk(c.f,d,s)==='불가');
// 희망 자리: 두 요일 모두 꼭/희망인 (요일 짝, 시각). 없으면 한쪽만 칠한 것
function wishedF(f){const both=[],part=[];
  for(const p of PKEYS)for(let s=0;s<SLOTS.length;s++){
    const ms=PAT[p].days.map(d=>mk(f,d,s));if(ms.includes('불가'))continue;
    if(isWant(ms[0])&&isWant(ms[1]))both.push({pat:p,slot:s});else if(isWant(ms[0])||isWant(ms[1]))part.push({pat:p,slot:s});}
  return both.length?both:part}
const wished=c=>wishedF(c.f);
const strengthF=f=>f.must?'꼭':'선호';
const wishOkAt=(c,p,s)=>{const W=wished(c);return !W.length||W.some(w=>w.pat===p&&w.slot===s)};
// 요일마다 희망 칸을 모으고, 희망 시각이 같은 요일끼리 묶어서 적는다 (예: 월·수 15:00)
function wishText(f,room=true){
  const groups=[];
  for(const d of D5){const ss=R(0,SLOTS.length-1).filter(s=>isWant(mk(f,d,s)));if(!ss.length)continue;
    const g=groups.find(x=>x.key===ss.join());if(g)g.days.push(d);else groups.push({key:ss.join(),days:[d],ss})}
  if(!groups.length)return '희망 시간 없음';
  const runs=ss=>{const o=[];let i=0;while(i<ss.length){let j=i;while(j+1<ss.length&&ss[j+1]===ss[j]+1)j++;o.push(i===j?SLOTS[ss[i]]:SLOTS[ss[i]]+'~'+endOf(ss[j]));i=j+1}return o.join(', ')};
  return groups.map(g=>`${g.days.map(d=>DAYN[d]).join('·')} ${runs(g.ss)}`).join(' / ')+(room&&f.pref&&f.pref.includes(' ')?' · '+f.pref:'')}
const wishLabel=c=>wishText(c.f);
function cellsOf(f,m){return Object.entries(f.paint).filter(([,v])=>v===m).map(([k])=>{const [d,s]=k.split('-').map(Number);return `${DAYN[d]} ${SLOTS[s]}`})}
function fJson(c){return JSON.stringify({분반:full(c),담당:c.prof+' 교수',희망자리:wishText(c.f,false),희망:cellsOf(c.f,'희망'),불가:cellsOf(c.f,'불가'),
  인원:c.f.size+'명',실습실:c.f.lab?'필요':'필요 없음',건물선호:c.f.pref,연강:CONSN[S.consec[c.prof]||'any'],기타요청:c.f.etc?'조교가 직접 확인 (자동 배정에 안 들어감)':null},null,1)}
/** @returns {any} */
function fChips(f,prof){const a=[],cnt=m=>Object.values(f.paint).filter(x=>x===m).length;
  a.push(wishedF(f).length?['희망 '+wishText(f,false),'good']:['희망 시간 없음 (아무 때나)','']);
  if(cnt('불가'))a.push([`불가 ${cnt('불가')}칸`,'bad']);
  a.push([`인원 ${f.size}명`,'']);
  if(f.lab)a.push(['실습실 필요','lab']);
  if(f.pref)a.push([f.pref.includes(' ')?f.pref:f.pref+' 선호','']);
  if(prof&&S.consec[prof]&&S.consec[prof]!=='any')a.push([CONSN[S.consec[prof]],'']);
  if(f.etc)a.push([f.etcOk?'기타 요청 · 조교 확인함':'기타 요청 · 조교 확인 전',f.etcOk?'good':'warn']);
  return a;}

// ---------------- NLP: 조율 회신 해석 (시안: 키워드 규칙으로 흉내. 실제는 backend/app/nlp/coord.py parse_reply) ----------------
// 돌려주는 모양은 API 명세 ReplyParse와 같다: {kind, picks, conditions:{day_slots, end_before}, note, method, fallback, fallback_reason}
const emptyCond=()=>({day_slots:{},end_before:[]});
const hasCond=k=>!!k&&(Object.keys(k.day_slots||{}).length>0||(k.end_before||[]).length>0);
const NOTE_RE=/[^.。!?\n]*(강의실\s*\d{3}|계단식|PC|컴퓨터|빔\s*프로젝터|마이크|칠판|조정\s*희망)[^.。!?\n]*/;
const winOf=t=>/늦은\s*오후/.test(t)?[5,7]:/오전/.test(t)?[0,1]:/저녁/.test(t)?[6,7]:/오후/.test(t)?[3,5]:null;
function parseReply(text,choice,alts,method){
  const t=(text||'').trim(),cond=emptyCond();
  let rest=t,picks=[...t.matchAll(/(?<![A-Za-z])([ABC])(?![A-Za-z])/g)].map(m=>m[1]);
  [...t.matchAll(/(첫|두|세)\s*번째/g)].forEach(m=>picks.push({첫:'A',두:'B',세:'C'}[m[1]]));
  if(choice&&choice!=='none')picks.unshift(choice);
  const none=choice==='none'||/(셋\s*다|모두|전부|다)\s*(어렵|안\s?되|안\s?돼|불가|힘들)/.test(t);
  picks=none?[]:[...new Set(picks)];
  for(const m of t.matchAll(/([월화수목금])요?일?[은는]?\s*(\d{1,2})시\s*(반)?\s*(?:전|이전|까지)/g)){
    rest=rest.replace(m[0],' ');
    const day=DAYN.indexOf(m[1]),lim=hr(+m[2])*60+(m[3]?30:0);
    // 고른 안이 15분 이내로만 넘기면 교수 재량으로 보고 조건에 넣지 않는다 (EARLY_END_MIN)
    const picked=picks.map(k=>(alts||[]).find(a=>a.k===k)).filter(a=>a&&PAT[a.pat].days.includes(day));
    if(picked.length&&picked.every(a=>endMin(a.slot)<=lim+EARLY_END_MIN))continue;
    cond.end_before.push({day,time:toHM(lim)});
  }
  if(!picks.length){
    const ds=[];[...rest.matchAll(/([월화수목금])(?=[·\s,\/요]|$)/g)].forEach(m=>{const d=DAYN.indexOf(m[1]);if(!ds.includes(d))ds.push(d)});
    const win=winOf(rest),ss=win?R(win[0],win[1]).map(i=>SLOTS[i]):[];
    (ds.length?ds.sort():win?D5:[]).forEach(d=>{cond.day_slots[String(d)]=ss});   // 빈 목록 = 그 요일은 아무 교시나
  }
  const neg=/(어렵|안\s?되|안\s?돼|불가|힘들)/.test(t);
  let kind=picks.length?(hasCond(cond)?'조건부':'수용'):(none||neg?'거절':hasCond(cond)?'조건부':'확인 필요');
  // 언어 모델: 시연 화면은 부르지 않는다. 장비·강의실 요청 문장만 note로 흉내 내고, '실패 흉내'를 켜면 fallback 규칙을 보여 준다
  let note='',used='keyword',fallback=false,fallback_reason='';
  if(method==='llm'){
    if(S.llmFail){fallback=true;fallback_reason='503 과부하';
      if(!(choice&&choice!=='none')&&(kind==='수용'||kind==='조건부')){note='';kind='확인 필요'}}
    else{used='llm';const m=t.match(NOTE_RE);if(m){note=m[0].trim();if(kind==='수용')kind='조건부'}}
  }
  return {kind,picks,conditions:cond,note,method:used,fallback,fallback_reason};
}
function condLabel(k){const a=[],ds=(k&&k.day_slots)||{},keys=Object.keys(ds).map(Number).sort();
  const sl=x=>!x.length?'':x.join()==='09:00,10:30'?' 오전':` ${x[0]}~${endOf(SLOTS.indexOf(x[x.length-1]))}`;
  if(keys.length){const same=keys.every(d=>ds[d].join()===ds[keys[0]].join());
    a.push(keys.length===5&&same?`요일 상관없이${sl(ds[keys[0]])}`:same?keys.map(d=>DAYN[d]).join('·')+'요일'+sl(ds[keys[0]]):keys.map(d=>DAYN[d]+sl(ds[d])).join(', '))}
  ((k&&k.end_before)||[]).forEach(e=>a.push(`${DAYN[e.day]}요일 ${e.time} 전 종료`));
  return a.join(', ');}
// 조건 검사: 요일이 둘 이상이면 그 요일들 안에서만, 하나면 그 요일이 들어가기만 하면 된다 (API 명세 day_slots)
function condOk(p,s,k){
  const days=PAT[p].days,ds=(k&&k.day_slots)||{},keys=Object.keys(ds);
  if(keys.length){const okDay=d=>(String(d) in ds)&&(!ds[d].length||ds[d].includes(SLOTS[s]));
    if(!(keys.length>=2?days.every(okDay):days.some(okDay)))return {ok:false,why:`${condLabel({day_slots:ds})} 조건과 어긋남`}}
  for(const e of (k&&k.end_before)||[])if(days.includes(e.day)&&endMin(s)>toMin(e.time))return {ok:false,why:`${DAYN[e.day]}요일 ${endOf(s)} 종료 → ${e.time} 전 종료 조건과 어긋남`};
  return {ok:true,why:'조건과 맞음'};
}
function mergeCond(a,b){a=a||emptyCond();b=b||emptyCond();
  const eb=[...a.end_before.filter(x=>!b.end_before.some(y=>y.day===x.day)),...b.end_before];
  return {day_slots:Object.keys(b.day_slots).length?b.day_slots:a.day_slots,end_before:eb}}

// ---------------- 솔버 (시안: 우선순위 순서 배정으로 흉내. 실제는 OR-Tools CP-SAT) ----------------
// 강의실은 요일마다 기록한다 (rooms = [앞 요일, 뒤 요일]). 실습실이 필요하면 실습실만, 정원이 인원보다 작은 방은 뺀다
const needLab=c=>!!c.f.lab;
function pairsFor(c){return ROOMS.filter(r=>r.cap>=(c.f.size||0)&&(!c.f.lab||r.lab)).map(r=>[r.id,r.id])}
// 희망 강의실을 콕 집어 적은 경우, 초안에서는 그 강의실만 본다 (못 쓰면 조율로)
function strictPairs(c){const pr=c.f.pref;if(!pr||!pr.includes(' '))return pairsFor(c);const P=ROOM(pr);
  return pairsFor(c).filter(rm=>rm.every((r,i)=>(needLab(c,i)||!P.lab)?r===pr:true));}
function clash(cid,p,s,rm){
  const c=C(cid),days=PAT[p].days;
  if(c.year===1&&s===CHAPEL.slot&&days.includes(CHAPEL.day))return {why:'채플 시간'};
  if(days.some(d=>isGenCell(d,s)))return {why:'교양필수 시간'};
  if(BLOCK){if(BLOCK.room&&rm.includes(BLOCK.room))return {why:'못 쓰는 강의실'};
    if(BLOCK.cells&&days.some(d=>BLOCK.cells.has(d+'-'+s)))return {why:'비우기로 한 시간'};}
  for(const o of S.courses){
    if(o.id===cid)continue;const a=S.assign[o.id];
    if(!a||a.slot!==s)continue;
    const od=PAT[a.pat].days,share=days.filter(d=>od.includes(d));if(!share.length)continue;   // 겹치는 요일이 있을 때만
    if(share.some(d=>a.rooms[od.indexOf(d)]===rm[days.indexOf(d)]))return {why:'강의실 겹침',by:o.id};
    if(o.prof&&o.prof===c.prof)return {why:'교수 겹침',by:o.id};
    if(o.year===c.year&&o.req&&c.req)return {why:'같은 학년 전공필수 겹침',by:o.id};
  }
  return null;
}
// 소프트 비용: 칠한 칸 + 희망 자리와의 거리 + 강의실 + 연강
// 희망 자리와의 거리: 시각 차이 + 희망에 없는 요일 하나당 3
function dist(c,p,s){const W=wished(c);if(!W.length)return 0;
  return Math.min(...W.map(w=>Math.abs(w.slot-s)+3*PAT[p].days.filter(d=>!PAT[w.pat].days.includes(d)).length));}
function roomCost(c,rm){let v=0;const pr=c.f.pref;
  rm.forEach((r,i)=>{const X=ROOM(r),nl=needLab(c,i);
    if(!nl&&X.lab)v+=3;
    if(pr){if(pr.includes(' ')){const Q=ROOM(pr);if(nl||!Q.lab)v+=r===pr?0:X.bldg===Q.bldg?2.25:3;else v+=X.bldg===Q.bldg?0:1.5}
      else v+=X.bldg===pr?0:1.5}
    v+=ROOMS.indexOf(X)*0.01;});
  return v+(rm[0]!==rm[1]?0.3:0);}
function consecCost(c,p,s){const k=S.consec[c.prof]||'any';if(k==='any')return 0;
  const adj=S.courses.some(o=>o.id!==c.id&&o.prof===c.prof&&S.assign[o.id]&&PAT[S.assign[o.id].pat].days.some(d=>PAT[p].days.includes(d))&&Math.abs(S.assign[o.id].slot-s)===1);
  return adj?(k==='avoid'?3:-1):0;}
function cost(c,p,s,rm){const cc=m=>isWant(m)?0:1;
  return PAT[p].days.reduce((v,d)=>v+cc(mk(c.f,d,s)),0)+dist(c,p,s)+roomCost(c,rm)+consecCost(c,p,s);}
function genAlts(c,k=emptyCond()){
  const list=[];
  for(const p of PKEYS)for(const s of R(0,SLOTS.length-1)){
    if(!hardOk(c,p,s)||!condOk(p,s,k).ok)continue;
    for(const rm of pairsFor(c)){if(clash(c.id,p,s,rm))continue;list.push({pat:p,slot:s,rooms:rm,score:cost(c,p,s,rm)})}}
  list.sort((a,b)=>a.score-b.score||a.slot-b.slot);
  const out=[],seen=new Set();
  for(const a of list){const key=a.pat+a.slot;if(!seen.has(key)){seen.add(key);out.push(a)}if(out.length===3)break}
  for(const a of list){if(out.length>=3)break;if(!out.includes(a))out.push(a)}
  return out.slice(0,3).map((a,i)=>({pat:a.pat,slot:a.slot,rooms:a.rooms,k:'ABC'[i]}));
}
function makeDraft(){
  S.assign={};S.status={};S.blocker={};S.reason={};S.why={};S.conds={};S.moved={};
  const allSpots=c=>PKEYS.flatMap(p=>R(0,SLOTS.length-1).map(s=>({pat:p,slot:s})));
  const spots=c=>{const W=wished(c);return W.length?W:allSpots(c)};
  const key=c=>(strengthF(c.f)==='꼭'?0:100)+(c.f.lab?0:50)+spots(c).length;
  const order=ACT().sort((a,b)=>key(a)-key(b)||S.courses.indexOf(a)-S.courses.indexOf(b));
  const bumped=[];
  for(const c of order){
    let best=null;
    for(const w of spots(c)){if(!hardOk(c,w.pat,w.slot))continue;
      for(const rm of strictPairs(c)){if(clash(c.id,w.pat,w.slot,rm))continue;const sc=cost(c,w.pat,w.slot,rm);
        if(!best||sc<best.sc)best={pat:w.pat,slot:w.slot,rooms:rm,sc};}}
    if(best){S.assign[c.id]={pat:best.pat,slot:best.slot,rooms:best.rooms};S.status[c.id]='done'}else bumped.push(c);
  }
  for(const c of bumped){
    const w=spots(c).filter(x=>hardOk(c,x.pat,x.slot))[0];
    const xs=w?strictPairs(c).map(rm=>clash(c.id,w.pat,w.slot,rm)).filter(Boolean):[];   // 어느 강의실이든 걸리는 이유(교수·전공필수)를 먼저 알린다
    const x=xs.find(y=>y.why!=='강의실 겹침')||xs[0]||{why:'자리 없음'};
    const b=x.by?C(x.by):null;
    const pr=!b?'':strengthF(b.f)==='꼭'&&strengthF(c.f)!=='꼭'?"상대 희망에 '꼭' 표시":b.f.lab&&!c.f.lab?'상대 강의가 실습실 필요':'종합 우선순위';
    S.blocker[c.id]=x.by||null;S.why[c.id]={by:x.by||null,why:x.why,pr};
    S.reason[c.id]=b?`${full(b)}(${b.prof} 교수)와 ${x.why} · 우선순위: ${pr}`:x.why;
    const alts=genAlts(c);
    if(alts.length){S.assign[c.id]={pat:alts[0].pat,slot:alts[0].slot,rooms:alts[0].rooms,temp:true};S.status[c.id]='open'}
  }
  S.stage='draft';S.lastChanged=[];
  log('초안',`초안을 자동으로 만들었습니다. 희망대로 ${ACT().length-bumped.length}개, 조율 필요 ${bumped.length}개 (${bumped.map(full).join(', ')}).`);
}
// ---------------- NLP: 조율 메시지 (시안: 틀에 값을 넣어 흉내. 실제는 LLM이 쓰고 코드가 검사) ----------------
function msgText(c,round,alts,b,k){
  const L=[`${c.prof} 교수님, 안녕하세요. 학과사무실입니다.`,`2027-1학기 ${full(c)} 분반 시간표 ${round}차 조율 안내드립니다.`,''];
  if(round===1)L.push(`희망하신 시간(${wishLabel(c)})이 ${S.reveal&&b?`${b.prof} 교수님의 ${b.name} ${b.sec} 분반과`:'다른 강의와'} 겹칩니다.`);
  else{L.push(hasCond(k)?`지난 회신에서 주신 조건(${condLabel(k)})을 반영해 대안을 다시 드립니다.`:'지난 차수 이후 바뀐 시간표를 반영해 대안을 다시 드립니다.');
    L.push(`처음 희망하신 시간: ${wishLabel(c)}`);}
  L.push('');
  alts.forEach(a=>L.push(`${a.k}  ${altLabel(a)}`));
  L.push('','가능한 안을 골라 주시거나, 모두 어려우시면 가능한 시간을 적어 주세요. 회신 기한은 1주이며, 기한 전에 한 번 더 알려 드립니다.');
  return L.join('\n');
}
function sendMsg(cid){
  const c=C(cid),b=S.blocker[cid]?C(S.blocker[cid]):null,alts=genAlts(c,S.conds[cid]||emptyCond());
  const text=msgText(c,S.round,alts,b,S.conds[cid]);
  S.msgs.push({id:'m'+(S.msgs.length+1),cid,round:S.round,alts,blocker:b?b.id:null,text,text0:text,sent:false,reply:null,parsed:null,decision:null});
}
// NLP: 메시지 검사 (API check_message 흉내). 빈 목록 = 통과
function checkMessage(text,m){
  const c=C(m.cid),b=m.blocker?C(m.blocker):null,p=[];
  if(/연차|임용|우선순위|경력|꼭 표시/.test(text))p.push('연차·임용·우선순위 같은 이유가 들어 있습니다');
  if(b&&b.f&&b.f.etc&&text.includes(b.f.etc))p.push('상대 교수의 기타 요청(메시지에 나오면 안 되는 글)이 들어 있습니다');
  if(!S.reveal&&b&&(text.includes(`${b.prof} 교수님`)||text.includes(full(b))))p.push('이름 숨김 설정인데 상대 교수·분반 이름이 들어 있습니다');
  if(!text.includes(full(c)))p.push(`과목·분반(${full(c)})이 빠졌습니다`);
  if(!text.includes(wishLabel(c)))p.push('본인 희망 시간이 빠졌습니다');
  const bad=m.alts.filter(a=>!text.includes(`${a.k}  ${altLabel(a)}`)).map(a=>a.k);
  if(bad.length)p.push(`대안 줄이 빠지거나 바뀌었습니다 (${bad.join('·')}안)`);
  return p;
}
function publish(){
  S.stage='round';S.round=1;
  Object.keys(S.status).filter(id=>S.status[id]==='open').forEach(sendMsg);
  log('1차 조율',`초안을 모든 교수에게 공개했습니다. 밀린 분반 ${openMsgs().length}건의 조율 메시지 초안을 만들었습니다. 조교가 확인하고 [보내기]를 눌러야 갑니다.`);
}
// ---------------- 최종 시간표 확정 요청 → 교수 [확정] 회신 ----------------
const profsWithCourses=()=>[...new Set(ACT().filter(c=>S.assign[c.id]).map(c=>c.prof))];
function confirmText(prof){
  const cs=ACT().filter(c=>c.prof===prof&&S.assign[c.id]);
  return [`${prof} 교수님, 안녕하세요. 학과사무실입니다.`,'2027-1학기 시간표 조율이 끝나 최종 시간표를 보내 드립니다.','',
    ...cs.map(c=>`- ${full(c)} · ${altLabel(S.assign[c.id])}`),'',
    '내용이 맞으면 [확정]을 눌러 회신해 주세요. 바꿔야 할 것이 있으면 회신에 적어 주시면 학과사무실에서 연락드리겠습니다.'].join('\n');
}
function sendConfirms(){
  S.confirms=profsWithCourses().map((prof,i)=>({id:'k'+(i+1),prof,text:confirmText(prof),reply:null,seen:false}));
  S.stage='confirm';
  log('확정 요청',`교수님 ${S.confirms.length}명께 최종 시간표와 확정 요청 메시지를 보냈습니다.`);
  S.confirms.forEach((k,i)=>later(()=>autoConfirm(k),i));
}
function receiveConfirm(k,note,from){
  if(k.reply)return;k.reply={note:note||'',from};
  log('확정 요청',`${k.prof} 교수님 확정${note?` · 메모 "${note}"`:''}${from==='조교 직접 처리'?' (조교가 직접 처리)':''}`);
  if(S.confirms.every(x=>x.reply)){S.stage='final';log('확정','모든 교수님이 확정했습니다. 엑셀로 내보내 SAP에 입력하면 됩니다.');toast('모든 교수님이 확정했습니다 · 내보낼 수 있습니다')}
}
// ---------------- 가상 회신 자동 도착 (시연용): 다른 화면에 있어도 알림과 메뉴 숫자로 알려 준다 ----------------
const AUTO_MS=4000,AUTO_GAP=2500;
function later(fn,i=0){if(S.autoReply)setTimeout(fn,AUTO_MS+i*AUTO_GAP)}
function autoReply(m){
  if(!S.msgs.includes(m)||m.reply||!m.sent||S.stage!=='round'||m.round!==S.round||!S.autoReply)return;
  const c=C(m.cid);if(S.role==='prof'&&S.prof===c.prof)return;   // 교수 화면에서 직접 답장하는 중이면 기다린다
  receive(m,(SCRIPT[m.round]||{})[m.cid]||'A로 할게요.',null,'가상 회신');
  log(`${m.round}차 조율`,`${full(c)}: ${c.prof} 교수님 답장 도착`);
  toast(`${c.prof} 교수님이 회신했습니다 · ${full(c)}`);notify();
}
function autoConfirm(k){
  if(!S.confirms.includes(k)||k.reply||S.stage!=='confirm'||!S.autoReply)return;
  if(S.role==='prof'&&S.prof===k.prof)return;
  receiveConfirm(k,'','가상 회신');
  if(S.stage!=='final')toast(`${k.prof} 교수님이 시간표를 확정했습니다`);
  notify();
}
// 조건 대조 → 처리안. 모양은 API 명세 Proposal과 같다: {action:'move'|'next'|'decide', key, conditions, text, checks:[{key,ok,why}]}
function check(m){
  const r=m.parsed,cond=r.conditions,last=S.round>=3;
  const decide=(checks,text)=>({action:'decide',key:null,conditions:cond,checks,text});
  const LAST='3차라 더 묻지 않습니다. [수정]이나 [현재대로 유지]로 정해 주세요.';
  if(r.kind==='확인 필요')return decide([],'답장을 확실히 읽지 못했습니다. [수정]으로 직접 정해 주세요.');
  if(r.picks.length){
    const checks=r.picks.map(key=>{const a=m.alts.find(x=>x.k===key);if(!a)return {key,ok:false,why:'없는 안'};
      const fit=condOk(a.pat,a.slot,cond);
      return fit.ok&&clash(m.cid,a.pat,a.slot,a.rooms)?{key,ok:false,why:'그사이 다른 강의가 들어감'}:{key,...fit}});
    const g=checks.find(x=>x.ok);
    if(g)return {action:'move',key:g.key,conditions:cond,checks,text:`${g.key}안(${altLabel(m.alts.find(x=>x.k===g.key))})으로 옮길까요?`};
    return last?decide(checks,LAST):{action:'next',key:null,conditions:cond,checks,text:'고른 안이 모두 조건과 어긋납니다. 조건을 넣어 다음 차수 대안을 만들까요?'};
  }
  if(last)return decide([],LAST);
  return {action:'next',key:null,conditions:cond,checks:[],text:hasCond(cond)?`새 조건(${condLabel(cond)})으로 다음 차수 대안을 만들까요?`:'다른 조건 없이 거절했습니다. 다음 차수 대안을 만들까요?'};
}
// 처리안 → 조교 결정 (내부 값)
const toDecision=(pr,kind)=>({kind,action:pr.action==='move'?{type:'move',k:pr.key}:{type:'next',conds:pr.conditions}});
function receive(m,text,choice,from){m.reply={text,choice:choice||null,from};m.parsed=parseReply(text,choice,m.alts,S.method);m.decision=null}
const sameSpot=(a,b)=>a.pat===b.pat&&a.slot===b.slot&&a.rooms.join()===b.rooms.join();
function resolveRound(){
  const prev=clone(S.assign),next=[],rd=S.round;S.peek=null;
  for(const m of openMsgs()){
    const c=C(m.cid),d=m.decision;
    if(!d){next.push(c.id);log(`${rd}차 재배정`,`${full(c)}: ${m.sent?'처리안 미확정':'메시지를 보내지 않음'} → 다음 차수에 다시 묻기`);continue}
    if(d.action.type==='move'){
      const a=m.alts.find(x=>x.k===d.action.k);
      if(!clash(c.id,a.pat,a.slot,a.rooms)){S.assign[c.id]={pat:a.pat,slot:a.slot,rooms:a.rooms};S.status[c.id]='done'}
      else{next.push(c.id);log(`${rd}차 재배정`,`${full(c)}: ${a.k}안 자리가 찼음 → 다음 차수`)}
    }else if(d.action.type==='keep'){S.assign[c.id].temp=false;S.status[c.id]='done'}
    else{S.conds[c.id]=mergeCond(S.conds[c.id],d.action.conds);next.push(c.id)}
  }
  S.lastChanged=S.courses.filter(c=>{const a=prev[c.id],b=S.assign[c.id];return a&&b&&!sameSpot(a,b)}).map(c=>c.id);
  log(`${rd}차 재배정`,`확인된 처리안만 반영하고 나머지 배정은 유지했습니다. 바뀐 분반 ${S.lastChanged.length}개${S.lastChanged.length?' ('+S.lastChanged.map(id=>full(C(id))).join(', ')+')':''}.`);
  if(next.length&&S.round<3){S.round++;next.forEach(sendMsg);log(`${S.round}차 조율`,`남은 ${next.length}건의 ${S.round}차 메시지 초안을 만들었습니다.`)}
  else{
    next.forEach(id=>{S.assign[id].temp=false;S.status[id]='done';log('확정',`${full(C(id))}: 3차 후 조교가 결정 (임시 배치 유지)`)});
    S.stage='review';log('조율 끝','남은 겹침이 없습니다. 최종 시간표를 교수님께 보내 확정을 받아 주세요.');
  }
}
function violations(){const set=new Set();
  for(const c of ACT()){const a=S.assign[c.id];if(!a)continue;const x=clash(c.id,a.pat,a.slot,a.rooms);
    if(x)set.add(x.by?[c.id,x.by].sort().join():c.id+x.why);if(!hardOk(c,a.pat,a.slot))set.add(c.id+'불가')}
  return set.size}
function exportCsv(){
  const rows=[['학년','과목','분반','교수','요일','시작','종료','강의실','비고']];
  ACT().forEach(c=>{const a=S.assign[c.id];if(!a)return;rows.push([c.year,c.name,c.sec,c.prof+' 교수',PAT[a.pat].label,SLOTS[a.slot],endOf(a.slot),roomText(a.pat,a.rooms),S.moved[c.id]?'AI 도우미로 조정':S.reason[c.id]?'조율 후 확정':''])});
  const csv='\uFEFF'+rows.map(r=>r.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\r\n');
  const u=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const a=document.createElement('a');a.href=u;a.download='SSUroom_2027-1_시간표_가상.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}

// ---------------- NLP: AI 도우미 (시안: 키워드 규칙으로 흉내. 실제는 LLM이 의도·정보를 JSON으로 뽑고 솔버 도구를 부름) ----------------
const ALIAS={객프:'c2',객체지향:'c2',자구:'c1',소공:'c11',운체:'c4',컴네:'c5',네트워크:'c5',자연어:'c3',인공지능:'c6',데베:'c7',디비:'c7',알고리즘:'c8',기계학습:'c9',머신러닝:'c9',컴구:'c10',이산:'c12',비전:'c13'};
function parseCmd(t){
  const q={intent:null,courses:[],prof:null,coref:false,alt:null,pat:null,day:null,slot:null,win:null,room:null,raw:t};
  for(const c of S.courses)if(t.includes(c.name))q.courses.push(c.id);
  for(const [a,id] of Object.entries(ALIAS))if(t.includes(a)&&!q.courses.includes(id))q.courses.push(id);
  const pm=t.match(/([가나다라마바사아자차카])\s*교수/);if(pm)q.prof=pm[1];
  q.coref=/그\s*(강의|수업|과목|분반|거)|그거|아까\s*(그|거|강의)|방금\s*(그|거|강의)/.test(t);
  const am=t.match(/(?<![A-Za-z])([ABC])(?![A-Za-z])/);if(am)q.alt=am[1];
  const pp=t.match(/([월화수목금])(?:요일)?\s*(?:과|와|하고|[·,\/])?\s*([월화수목금])(?!업|정|강|학)/);
  if(pp&&pp[1]!==pp[2])q.pat=patOf(DAYN.indexOf(pp[1]),DAYN.indexOf(pp[2]));
  else{const dm=t.match(/([월화수목금])요일/)||t.match(/(?:^|\s)([월화수목금])(?=\s|$)/);if(dm)q.day=DAYN.indexOf(dm[1])}
  const tm=t.match(/(\d{1,2})(?::(\d{2})|\s*시(\s*반)?)/);if(tm)q.slot=slotOf(hr(+tm[1]),tm[2]?+tm[2]:tm[3]?30:0);
  if(/오전/.test(t))q.win=[0,1];else if(/저녁/.test(t))q.win=[6,7];else if(/오후/.test(t))q.win=[3,5];
  const rm=t.match(/(201|410|210|305|306)/);if(rm)q.room=ROOMS.find(r=>r.id.endsWith(rm[1])).id;
  if(/왜|이유|어째서/.test(t))q.intent='explain';
  else if(q.room&&/(못\s*쓰|공사|막|빼|없으면|안\s*되|닫)/.test(t))q.intent='room';
  else if((q.day!=null||q.pat)&&!q.courses.length&&!q.coref&&!q.prof&&/(비우|빼|막|안\s*되|없애|쉬)/.test(t))q.intent='block';
  else if(/(옮기|옮겨|바꾸|바꿔|이동|넣어|넣으)/.test(t))q.intent=/(면|어때|될까|\?)/.test(t)?'whatif':'move';
  else if(/(뭐|몇|목록|남은|현황|상황|어디|있어|알려)/.test(t))q.intent='status';
  return q;
}
const hasInfo=q=>q.courses.length||q.prof||q.coref||q.alt||q.room||q.slot!=null||q.pat||q.day!=null||q.win;
function botRun(text){
  const b=S.bot;b.turns.push({who:'ta',text});
  let q=parseCmd(text);
  if(!q.intent&&b.pending&&hasInfo(q)){const p=b.pending;
    q={...p,courses:q.courses.length?q.courses:p.courses,prof:q.prof||p.prof,coref:q.coref||p.coref,alt:q.alt||p.alt,pat:q.pat||p.pat,
       day:q.day??p.day,slot:q.slot??p.slot,win:q.win||p.win,room:q.room||p.room,raw:p.raw+' → '+text,merged:true};}
  b.pending=null;
  b.turns.push(botAnswer(q));
}
// 지금 시간표에서 바뀐 것만 고치기: 고정한 분반은 두고, 규칙에 걸리는 분반만 가장 가까운 대안으로 옮긴다
function repair(fixed){
  for(let it=0;it<8;it++){let moved=false;
    for(const o of ACT()){
      if(fixed.has(o.id))continue;const a=S.assign[o.id];if(!a)continue;
      if(!clash(o.id,a.pat,a.slot,a.rooms)&&hardOk(o,a.pat,a.slot))continue;
      const alts=genAlts(o,S.conds[o.id]||{});if(!alts.length){FAIL=o.id;return false}
      S.assign[o.id]={pat:alts[0].pat,slot:alts[0].slot,rooms:alts[0].rooms,temp:a.temp};fixed.add(o.id);moved=true;}
    if(!moved)return true;}
  return false;
}
function sim(fn){
  const base=clone(S.assign);FAIL=null;let ok=false,after;
  try{ok=fn()}finally{after=clone(S.assign);S.assign=base;BLOCK=null}
  const changes=ACT().filter(c=>base[c.id]&&after[c.id]&&!sameSpot(base[c.id],after[c.id])).map(c=>({cid:c.id,from:base[c.id],to:after[c.id]}));
  S.assign=after;const v=violations();S.assign=base;
  return {ok,after,changes,v};
}
function bestRooms(c,p,s,want){let ps=pairsFor(c);if(want)ps=ps.filter(rm=>rm.includes(want));if(!ps.length)return null;
  const free=ps.filter(rm=>!clash(c.id,p,s,rm)),pool=free.length?free:ps;
  return pool.slice().sort((x,y)=>cost(c,p,s,x)-cost(c,p,s,y))[0];}
function explainText(c){
  const a=S.assign[c.id];if(!a)return `${jo(full(c),'은','는')} 아직 배정 전입니다.`;
  const here=altLabel(a),w=S.why[c.id];
  if(S.moved[c.id])return `${jo(full(c),'은','는')} 조교가 AI 도우미로 ${ro(here)} 옮겼습니다 (${S.moved[c.id]}).`;
  if(w){const b=w.by?C(w.by):null,first=`희망하신 ${wishLabel(c)}`;
    const HIT={'강의실 겹침':'강의실이 겹쳤습니다','교수 겹침':'담당 교수가 같아 시간이 겹쳤습니다','같은 학년 전공필수 겹침':'같은 학년 전공필수라 시간이 겹쳤습니다'};
    const hit=b?`${full(b)}(${b.prof} 교수)와 ${HIT[w.why]||w.why}`:`${w.why} 때문에 자리가 없었습니다`;
    if(S.status[c.id]==='open')return `${full(c)}: ${jo(first,'이','가')} ${hit}. 우선순위(${w.pr})에 따라 이 강의가 밀렸고, 지금은 ${here}에 임시로 두고 ${S.stage==='round'?S.round+'차 조율 중':'조율을 기다리는 중'}입니다.`;
    return `${full(c)}: ${jo(first,'이','가')} ${hit}. 조율을 거쳐 지금 자리(${here})로 정했습니다.`;}
  const notes=[];
  if(c.f.pref&&c.f.pref.includes(' ')&&a.rooms.includes(c.f.pref))notes.push('희망 강의실도 그대로입니다');
  return `${jo(full(c),'은','는')} ${c.prof} 교수님이 칠한 희망 시간(${wishText(c.f,false)}) 안에서 규칙에 걸리지 않는 자리라 ${here}에 배정했습니다.${notes.length?' '+notes.join(', ')+'.':''}`;
}
function statusText(c,prof){
  const spot=x=>{const a=S.assign[x.id];return a?`${altLabel(a)}${S.status[x.id]==='open'?' (조율 중, 임시)':''}`:'배정 전'};
  if(c)return `${jo(full(c),'은','는')} 지금 ${spot(c)}입니다.`;
  if(prof){const cs=ACT().filter(x=>x.prof===prof);return cs.length?`${prof} 교수님 강의는 ${cs.length}개입니다. `+cs.map(x=>`${full(x)}: ${spot(x)}`).join(' / '):`${prof} 교수님이 맡은 강의가 없습니다.`}
  const dup=S.courses.filter(x=>x.own==='dup').length,none=S.courses.filter(x=>x.own==='none').length;
  if(S.stage==='collect')return `희망 수집 중입니다. 담당 겹침 ${dup}건, 담당 없음 ${none}건, 기타 요청 확인 ${etcTodo()}건이 남았습니다.`;
  const open=ACT().filter(x=>S.status[x.id]==='open');
  return `조율 중인 분반은 ${open.length}개${open.length?` (${open.map(x=>`${full(x)} · ${x.prof} 교수`).join(', ')})`:''}이고, 하드 규칙 위반은 ${violations()}건입니다.`+(S.stage==='round'?` ${S.round}차 회신 대기 ${openMsgs().filter(m=>!m.reply).length}건.`:'');
}
function withPreview(T,r,lead,target,raw){
  T.solver=r.ok?`바뀌는 분반 ${r.changes.length}개 · 하드 규칙 위반 ${r.v}건`:'계산 실패';
  if(!r.ok){T.text=FAIL?`${lead} ${jo(full(C(FAIL)),'을','를')} 둘 다른 자리가 없어서 할 수 없습니다.`:`${lead} 규칙을 지키는 배치를 찾지 못했습니다.`;return T}
  if(!r.changes.length){T.text=`${lead} 바뀌는 분반이 없습니다.`;return T}
  const miss=r.changes.filter(x=>!wishOkAt(C(x.cid),x.to.pat,x.to.slot));
  const notice=r.changes.filter(x=>x.cid!==target&&S.status[x.cid]==='done');
  T.text=`${lead} ${r.changes.length}개 분반이 바뀌고 하드 규칙 위반은 ${r.v}건입니다. `
    +(miss.length?`희망 시간 밖으로 가는 분반은 ${miss.length}개(${miss.map(x=>full(C(x.cid))).join(', ')})입니다.`:'바뀌는 분반은 모두 교수님 희망 시간 안입니다.')
    +(notice.length?` ${notice.map(x=>`${full(C(x.cid))}(${C(x.cid).prof} 교수)`).join(', ')}는 이미 정해진 강의라, 적용하면 교수님께 변경 안내가 필요합니다.`:'');
  T.preview={changes:r.changes,after:r.after,base:JSON.stringify(S.assign),state:null,target,raw,v:r.v,notice:notice.length};
  return T;
}
function botAnswer(q){
  const IN={explain:'이유 설명',room:'가정 실행',block:'가정 실행',whatif:'가정 실행',move:'이동',status:'현황 조회'};
  const T={who:'bot',intent:q.intent?IN[q.intent]:'범위 밖',info:{},tool:null,solver:null,text:''};
  if(!q.intent){
    if(hasInfo(q)){T.intent='확인 필요';T.text='무엇을 할지 알려 주세요. 예: "왜 여기야?", "B안으로 옮겨", "화·목 10:30으로 옮기면?"';S.bot.pending=q;return T}
    T.text='시간표 편성·조율과 관련된 요청만 처리합니다. 예: "객체지향은 왜 밀렸어?", "화요일 오전 비우면?"';return T}
  let ids=q.courses.slice();
  if(!ids.length&&q.coref&&S.bot.last){ids=[S.bot.last];T.info['그 강의']=full(C(S.bot.last))}
  if(!ids.length&&q.prof){ids=S.courses.filter(c=>c.prof===q.prof).map(c=>c.id);T.info.교수=q.prof+' 교수'}
  if(['explain','whatif','move'].includes(q.intent)&&ids.length!==1){
    T.ask=true;S.bot.pending={...q,courses:[],prof:null,coref:false};
    T.text=ids.length>1?`${q.prof?q.prof+' 교수님 강의가':'해당하는 강의가'} ${ids.length}개입니다: ${ids.map(id=>full(C(id))).join(', ')}. 어느 강의인가요?`:'어느 강의인가요? 과목 이름으로 알려 주세요.';
    return T}
  if(q.intent==='status'&&!q.courses.length&&!T.info['그 강의']&&q.prof){
    T.tool=`status(교수="${q.prof}")`;T.solver='현재 시간표 조회';T.text=statusText(null,q.prof);return T}
  const c=ids.length===1?C(ids[0]):null;
  if(c){if(!T.info['그 강의'])T.info.분반=full(c);S.bot.last=c.id}
  if(q.intent==='status'){
    T.tool=c?`status(분반="${full(c)}")`:'status()';T.solver='현재 시간표 조회';
    T.text=statusText(c,null);return T}
  if(S.stage==='collect'){T.text='아직 초안이 없습니다. 희망 확인을 마치고 초안을 만든 뒤에 계산할 수 있습니다.';return T}
  if(c&&c.own!=='ok'){T.text=`${jo(full(c),'은','는')} 담당 교수가 정해지지 않아 배정 전입니다.`;return T}
  if(q.intent==='explain'){T.tool=`explain(분반="${full(c)}")`;T.solver='배정 기록 조회';T.text=explainText(c);return T}
  if(q.intent==='whatif'||q.intent==='move'){
    const cur=S.assign[c.id];let tgt=null;
    if(q.alt){const m=S.msgs.filter(x=>x.cid===c.id).slice(-1)[0],alts=m?m.alts:genAlts(c,S.conds[c.id]||{}),a=alts.find(x=>x.k===q.alt);
      T.info.대안=q.alt+'안';if(!a){T.text=`${full(c)}에는 ${q.alt}안이 없습니다.`;return T}tgt={pat:a.pat,slot:a.slot,rooms:a.rooms}}
    else if(q.slot!=null||q.pat||q.day!=null||q.room||q.win){
      if(q.day!=null&&!q.pat&&!PAT[cur.pat].days.includes(q.day)){T.ask=true;S.bot.pending={...q,courses:[c.id],day:null};
        T.text=`수업이 주 2회라 요일이 두 개 필요합니다. ${DAYN[q.day]}요일과 어느 요일로 할까요? 예: "${PAT[patOf(q.day,q.day===4?1:4)].label}"`;return T}
      const pat=q.pat||cur.pat;
      tgt={pat,slot:q.slot??(q.win?q.win[0]:cur.slot),room:q.room}}
    if(!tgt){T.ask=true;S.bot.pending={...q,courses:[c.id]};T.text=`${jo(full(c),'을','를')} 어디로 옮길까요? 예: "화·목 10:30", "B안"`;return T}
    const lbl=`${PAT[tgt.pat].label} ${SLOTS[tgt.slot]}${tgt.room?' · '+tgt.room:''}`;T.info.목표=lbl;
    T.tool=`move(분반="${full(c)}", 요일="${PAT[tgt.pat].label}", 시작="${SLOTS[tgt.slot]}"${tgt.room?`, 강의실="${tgt.room}"`:''})`;
    if(!hardOk(c,tgt.pat,tgt.slot)){T.solver='거부: 교수 불가 시간';T.text=`${PAT[tgt.pat].label} ${SLOTS[tgt.slot]}은 ${c.prof} 교수님이 불가로 칠한 시간이라 옮길 수 없습니다.`;return T}
    if(c.year===1&&tgt.slot===CHAPEL.slot&&PAT[tgt.pat].days.includes(CHAPEL.day)){T.solver='거부: 채플 시간';T.text='1학년 채플 시간(목 12:00)이라 옮길 수 없습니다.';return T}
    if(PAT[tgt.pat].days.some(d=>isGenCell(d,tgt.slot))){T.solver='거부: 교양필수 시간';T.text='화·목 12:00은 교양필수 시간(가상 규칙)이라 전공을 둘 수 없습니다.';return T}
    const rm=tgt.rooms||bestRooms(c,tgt.pat,tgt.slot,tgt.room);
    if(!rm){T.solver='거부: 강의실 조건';T.text=`${jo(tgt.room,'은','는')} ${c.f.lab?'실습실이 아니거나 ':''}정원이 인원(${c.f.size}명)보다 작아 ${full(c)}을(를) 둘 수 없습니다.`;return T}
    const r=sim(()=>{S.assign[c.id]={pat:tgt.pat,slot:tgt.slot,rooms:rm,temp:false};return repair(new Set([c.id]))});
    const to=r.after[c.id];
    return withPreview(T,r,`${jo(full(c),'을','를')} ${q.alt?`${q.alt}안(${altLabel(to)})으로`:ro(altLabel(to))} 옮기면`,c.id,q.raw);
  }
  if(q.intent==='block'){
    const days=q.pat?PAT[q.pat].days:[q.day],ss=q.slot!=null?[q.slot]:q.win?R(q.win[0],q.win[1]):R(0,SLOTS.length-1);
    const lbl=`${days.map(d=>DAYN[d]).join('·')}요일 ${ss.length===SLOTS.length?'전체':ss.length===1?SLOTS[ss[0]]:SLOTS[ss[0]]+'~'+endOf(ss[ss.length-1])}`;
    T.info['비울 시간']=lbl;T.tool=`what_if(비울 시간="${lbl}")`;
    const r=sim(()=>{BLOCK={cells:new Set(days.flatMap(d=>ss.map(s=>d+'-'+s)))};return repair(new Set())});
    return withPreview(T,r,`${jo(lbl,'을','를')} 비우면`,null,q.raw);
  }
  if(q.intent==='room'){
    T.info.강의실=q.room;T.tool=`what_if(못 쓰는 강의실="${q.room}")`;
    const r=sim(()=>{BLOCK={room:q.room};return repair(new Set())});
    return withPreview(T,r,`${jo(q.room,'을','를')} 못 쓰면`,null,q.raw);
  }
  return T;
}

// ---------------- 화면이 읽는 값 ----------------
// 아직 적용하지 않은 가장 최근 AI 도우미 미리보기 (패널이 열려 있고 시간표가 그대로일 때만)
function livePreview(){
  if(S.role!=='ta'||!S.botOpen)return null;
  for(let i=S.bot.turns.length-1;i>=0;i--){const p=S.bot.turns[i].preview;if(p)return !p.state&&p.base===JSON.stringify(S.assign)?p:null}
  return null;
}
// 조율 대안 미리 보기: 조교가 고른 안으로 옮기면 어디로 가는지 (아직 반영 전)
function peekInfo(){
  if(!S.peek||S.stage!=='round')return null;
  const m=S.msgs.find(x=>x.id===S.peek.m);if(!m||!openMsgs().includes(m))return null;
  const a=m.alts.find(x=>x.k===S.peek.k);if(!a)return null;
  const to={pat:a.pat,slot:a.slot,rooms:a.rooms},cur=S.assign[m.cid],hit=clash(m.cid,a.pat,a.slot,a.rooms);
  return {m,cid:m.cid,k:a.k,to,same:!!cur&&sameSpot(cur,to),hit};
}
/** @returns {any} */
function navItems(){
  if(S.role==='ta'){
    const flags=S.stage==='collect'?todo():0, pend=openMsgs().filter(m=>m.reply&&!m.decision).length;
    const conf=S.confirms.filter(k=>k.reply&&!k.seen).length;
    return [['home','현황'],['wishes','희망 확인',flags],['draft','시간표'],['coord','조율',pend],['final','확정·내보내기',conf],['settings','설정']];
  }
  const unread=S.msgs.filter(m=>m.sent&&C(m.cid).prof===S.prof&&m.round===S.round&&S.stage==='round'&&!m.reply).length
    +S.confirms.filter(k=>k.prof===S.prof&&!k.reply&&S.stage==='confirm').length;
  return [['pwish','희망 입력'],['ptable','공개 시간표'],['pmsg','조율 메시지',unread]];
}
const toApiAlt=a=>({key:a.k,meetings:PAT[a.pat].days.map((d,i)=>({day:d,start:SLOTS[a.slot],end:endOf(a.slot),room:a.rooms[i]}))});
const blockedCell=(year,d,s)=>isGenCell(d,s)?'교양':year===1&&d===CHAPEL.day&&s===CHAPEL.slot?'채플':'';

// ---------------- 동작 (2단계에서 서버 호출로 바뀌는 곳) ----------------
function applyBot(i,reason){
  const p=S.bot.turns[i].preview;
  if(JSON.stringify(S.assign)!==p.base){p.state='stale';toast('그사이 시간표가 바뀌어 다시 계산해야 합니다');return}
  S.assign=clone(p.after);
  for(const ch of p.changes){const id=ch.cid;S.assign[id].temp=false;S.moved[id]=`요청 "${p.raw}" · 사유 "${reason}"`;
    if(S.status[id]==='open'){S.status[id]='done';openMsgs().filter(x=>x.cid===id&&!x.decision).forEach(x=>x.decision={kind:'AI 도우미로 옮김',action:{type:'keep'},reason})}}
  S.lastChanged=p.changes.map(x=>x.cid);p.state='applied';
  log('AI 도우미',`"${p.raw}" 적용 · 사유 "${reason}" · 바뀐 분반 ${p.changes.length}개 (${p.changes.map(x=>full(C(x.cid))).join(', ')}).`);
  toast(`적용했습니다 · 바뀐 분반 ${p.changes.length}개`);
}
function sendOne(m,i=0){const ps=checkMessage(m.text,m);if(ps.length)return false;m.sent=true;log(`${m.round}차 조율`,`${full(C(m.cid))}: ${C(m.cid).prof} 교수님께 조율 메시지를 보냈습니다.`);later(()=>autoReply(m),i);return true}
function reparse(){openMsgs().filter(m=>m.reply&&!m.decision).forEach(m=>{m.parsed=parseReply(m.reply.text,m.reply.choice,m.alts,S.method)})}
const msgById=id=>S.msgs.find(x=>x.id===id);
// 칠하기: 묶기를 켰으면 짝 요일(월↔수, 화↔목) 칸도 같은 값으로. 교양필수·채플 칸은 건너뛴다
function setOne(x,d,k,mark){const key=d+'-'+k;if(mark)x.f.paint[key]=mark;else delete x.f.paint[key]}
function setMark(x,d,k,mark){setOne(x,d,k,mark);
  const pr=S.pair[x.cid]||{},q=PARTNER[d];if(q==null)return;
  if(((d===0||d===2)&&pr.mw)||((d===1||d===3)&&pr.tt)){if(!blockedCell(C(x.cid).year,q,k))setOne(x,q,k,mark)}}
const nextMark=cur=>CYC[(CYC.indexOf(cur)+1)%CYC.length];

// ---------------- 분반 수 (조교가 과목마다 연다) ----------------
const secKey=(prof,name)=>prof+'|'+name;
/** 과목 이름별로 묶은 목록: [{name,year,req,secs:[course...]}] */
function courseGroups(){const g=new Map();
  for(const c of S.courses){if(!g.has(c.name))g.set(c.name,{name:c.name,year:c.year,req:c.req,secs:[]});g.get(c.name).secs.push(c)}
  return [...g.values()].map(x=>({...x,secs:[...x.secs].sort((a,b)=>a.sec.localeCompare(b.sec))}))}
/** 한 과목의 분반 수를 n개로 맞춘다. 늘리면 빈 번호로 새 분반, 줄이면 번호가 큰 분반부터 뺀다 (그 분반의 희망도 같이) */
function setSecCount(name,n){
  const grp=courseGroups().find(x=>x.name===name);if(!grp)return;
  const want=Math.max(1,Math.min(MAX_SECTIONS,Math.floor(n)||1)),secs=grp.secs;
  if(want>secs.length){const used=new Set(secs.map(c=>c.sec));
    let next=S.courses.reduce((m,c)=>Math.max(m,Number(c.id.slice(1))||0),0);
    for(let k=1,add=want-secs.length;add>0;k++){const sec=String(k).padStart(2,'0');if(used.has(sec))continue;
      S.courses.push({id:'c'+(++next),name,sec,year:grp.year,req:grp.req});add--}}
  else if(want<secs.length){const gone=new Set(secs.slice(want).map(c=>c.id));
    S.courses=S.courses.filter(c=>!gone.has(c.id));S.claims=S.claims.filter(x=>!gone.has(x.cid));
    for(const id of gone){delete S.pick[id];delete S.excl[id]}}
  sync();log('희망 수집',`${name} 분반을 ${want}개로 정했습니다.`)}
/** 이 교수가 같은 과목에서 둘 이상 고른 과목 이름들 */
function multiSecNames(prof){const cnt={};
  for(const x of S.claims)if(x.prof===prof){const nm=C(x.cid).name;cnt[nm]=(cnt[nm]||0)+1}
  return Object.keys(cnt).filter(k=>cnt[k]>=2)}

export {
  SLOTS,DAYN,D5,PAT,ROOMS,BLDGS,PRIO,RULES,MARKS,CONSN,SIZES,PROFS,SCRIPT,BOT_EX,
  sync,ACT,claimOf,etcTodo,todo,C,full,altLabel,roomText,endOf,log,stageIdx,openMsgs,mk,mcls,wishText,wishLabel,
  fJson,fChips,emptyCond,hasCond,condLabel,makeDraft,checkMessage,publish,profsWithCourses,confirmText,sendConfirms,
  receiveConfirm,later,autoReply,check,toDecision,receive,resolveRound,violations,exportCsv,botRun,wishOkAt,kindOf,
  mkClaim,emptyF,genAlts,livePreview,peekInfo,navItems,toApiAlt,blockedCell,applyBot,sendOne,reparse,msgById,
  setMark,nextMark,isGenCell,CYC,SECMODE,SECMODE_TIP,MAX_SECTIONS,secKey,courseGroups,setSecCount,multiSecNames
}
