import { useEffect, useState } from "react";
import { fetchCourses, fetchGroups, queueGroupPath, queueRequest } from "../../api";
import { usePolling } from "./usePolling";
import { displayDate, entryLabel } from "./state";
import "./queue.css";

const coursePath = id => `/admin/courses/${encodeURIComponent(id)}/queue`;
const eventNames = { called: "Вызван", defended: "Защитил", failed: "Не защитил", no_show: "Не явился", withdrawn: "Исключён", added_to_tail: "Добавлен в конец", roster_frozen: "Состав зафиксирован", schedule_changed: "Занятие перенесено", enrollment_closed:"Запись закрыта", enrollment_opened:"Запись открыта", cancelled: "Занятие отменено", sheet_defended: "Защита подтверждена таблицей", session_finished: "Ожидание завершено" };

export function TeacherQueue({ initialCourse = "" }) {
  const [courses, setCourses] = useState([]), [course, setCourse] = useState(initialCourse);
  const [groups, setGroups] = useState([]), [group, setGroup] = useState("");
  const [sessionId, setSessionId] = useState(""), [tab, setTab] = useState("queue");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const sessions = usePolling("/admin/queue/sessions");
  const path = course && group ? queueGroupPath(course, group, true) : null;
  const roster = usePolling(path && sessionId ? `${path}?session_id=${encodeURIComponent(sessionId)}` : null);
  const [settingsVersion, setSettingsVersion] = useState(0);
  useEffect(() => { let alive = true; fetchCourses("all").then(rows => { if (alive) { setCourses(rows); setCourse(value => value || rows[0]?.id || ""); } }).catch(err => setError(err.message)); return () => { alive = false; }; }, []);
  useEffect(() => {
    let alive = true; setGroups([]); setGroup(""); setSessionId("");
    if (course) fetchGroups(course).then(rows => { if (alive) { setGroups(rows); setGroup(rows[0] || ""); } }).catch(err => { if (alive) setError(err.message); });
    return () => { alive = false; };
  }, [course]);
  const filtered = (sessions.data || []).filter(s => s.course_id === course && s.group_id === group).sort((a,b) => a.starts_at-b.starts_at);
  useEffect(() => {
    if (!filtered.some(s => s.session_id === sessionId)) {
      const now = Date.now()/1000;
      setSessionId((filtered.find(s => s.starts_at <= now && s.ends_at > now && s.enrollment_status !== "cancelled") || filtered.find(s => s.starts_at > now && s.enrollment_status !== "cancelled") || filtered.at(-1))?.session_id || "");
    }
  }, [course, group, sessions.data, sessionId]);
  async function perform(task) {
    setBusy(true); setError("");
    try { await task(); roster.refresh(); sessions.refresh(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  const action = payload => perform(() => queueRequest(`${path}/actions`, { method:"POST", body:{ session_id:sessionId, ...payload } }));
  const data = roster.data;
  return <main className="queue-surface queue-admin">
    <a href="/admin/courses">← Предметы</a>
    <h1>Защита лабораторных</h1>
    <p className="queue-muted">Полный состав занятия, результаты и расписание.</p>
    <div className="queue-toolbar">
      <label>Предмет<select value={course} onChange={e => setCourse(e.target.value)}>{courses.map(c => <option key={c.id} value={c.id}>{c.name || c.id}</option>)}</select></label>
      <label>Группа<select value={group} onChange={e => { setGroup(e.target.value); setSessionId(""); }}>{groups.map(g => <option key={g}>{g}</option>)}</select></label>
      <label>Занятие<select value={sessionId} onChange={e => setSessionId(e.target.value)}><option value="">Выберите занятие</option>{filtered.map(s => <option key={s.session_id} value={s.session_id}>{displayDate(s.starts_at,s.timezone)}{s.enrollment_status === "cancelled" ? " · отменено" : ""}</option>)}</select></label>
    </div>
    <nav className="queue-tabs" aria-label="Разделы панели">{[["queue","Очередь"],["schedule","Расписание"],["settings","Дедлайны и порядок"]].map(([key,label]) => <button key={key} aria-current={tab===key ? "page" : undefined} className={tab===key ? "primary" : ""} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {(error || sessions.error || roster.error) && <p role="alert" className="queue-notice queue-error">{error || sessions.error?.message || roster.error?.message} <button onClick={() => { roster.refresh(); sessions.refresh(); }}>Повторить</button></p>}
    {busy && <p role="status">Сохраняется…</p>}
    {tab === "queue" && <>
      {!sessionId && <p className="queue-notice">Назначьте занятие во вкладке «Расписание».</p>}
      {sessionId && !data && !roster.error && <p role="status">Загружается очередь…</p>}
      {data && <>
        <h2>{displayDate(data.session.starts_at,data.session.timezone)} · {group}</h2>
        <p>{data.mode === "random" ? "Случайный порядок" : "Приоритет по дедлайнам, от −1"}. {data.attendance_open ? "Студенты могут менять посещение до начала пары." : "Состав зафиксирован; изменения доступны преподавателю."}</p>
        {data.stale && <p className="queue-notice">Таблица недоступна. Показан сохранённый состав, обновление допуска ожидается.</p>}
        {Date.now()/1000 < data.session.starts_at && data.session.enrollment_status !== "cancelled" && <button disabled={busy} onClick={() => action({action:data.session.enrollment_status === "closed" ? "open_enrollment" : "close_enrollment"})}>{data.session.enrollment_status === "closed" ? "Открыть запись" : "Закрыть запись досрочно"}</button>}
        <dl className="queue-summary">{[["waiting","Ждут"],["defended","Защитили"],["failed","Не защитили"],["no_show","Не явились"]].map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{data.stats[key]}</dd></div>)}</dl>
        <button className="primary" disabled={busy || Date.now()/1000 < data.session.starts_at || !data.next_entry_id || Boolean(data.current_entry_id)} onClick={() => action({action:"call_next"})}>Вызвать следующего</button>
        <div className="queue-table-wrap"><table className="queue-table"><caption className="queue-sr-only">Все участники и результаты выбранного занятия</caption><thead><tr><th>Позиция</th><th>Студент / GitHub</th><th>Работа</th><th>Допущен</th><th>Статус</th><th>Действия</th></tr></thead><tbody>
          {data.entries.map((row,index) => {
            const current = row.attempt?.entry_id === data.current_entry_id, next = row.attempt?.entry_id === data.next_entry_id;
            const active = ["waiting","called"].includes(row.attempt?.status);
            return <tr key={row.candidate_id} className={`${current ? "current" : next ? "next" : row.state} ${row.attempt?.is_repeat ? "repeat" : ""}`}>
              <td>{active ? index+1 : row.position ?? "—"}</td><td><strong>{row.full_name}</strong><br/><a href={`https://github.com/${encodeURIComponent(row.github)}`} target="_blank" rel="noreferrer">{row.github}</a></td><td>{row.lab_key}{row.priority != null && <small><br/>Приоритет {row.priority}</small>}</td><td>{displayDate(row.qualified_at,data.session.timezone)}</td><td>{entryLabel(row,{current:data.current_entry_id,next:data.next_entry_id})}</td>
              <td><div className="queue-actions">{current && [["defended","Сдал"],["failed","Не сдал"],["no_show","Не пришёл"]].map(([outcome,label]) => <button key={outcome} disabled={busy} onClick={() => action({action:"result",entry_id:row.attempt.entry_id,outcome})}>{label}</button>)}
                {active ? <button disabled={busy} onClick={() => action({action:"withdraw",entry_id:row.attempt.entry_id})}>Убрать</button> : <button disabled={busy || Date.now()/1000 >= data.session.ends_at || data.session.enrollment_status === "cancelled"} onClick={() => action({action:"add_tail",candidate_id:row.candidate_id})}>В конец</button>}
              </div></td></tr>;
          })}
        </tbody></table></div>
        {!data.entries.length && <p>Участников пока нет.</p>}
        <details><summary>История и попытки</summary>
          <ul className="queue-history">{data.history.map(e => <li key={e.event_id}>{displayDate(e.occurred_at,data.session.timezone)} · {eventNames[e.kind] || e.kind}{e.full_name ? ` · ${e.full_name} · работа ${e.lab_key}` : ""}{e.entry_id ? ` · попытка ${e.entry_id}` : ""}</li>)}</ul>
          <p>Сверка с таблицей: {data.reconciliation?.done_at ? displayDate(data.reconciliation.done_at,data.session.timezone) : data.reconciliation?.error ? "ожидается повтор после ошибки чтения" : "через 10 минут после окончания"}.</p>
        </details>
      </>}
    </>}
    {tab === "schedule" && <Schedule course={course} group={group} sessions={sessions.data || []} perform={perform} busy={busy} version={settingsVersion} onSaved={() => setSettingsVersion(v => v+1)} />}
    {tab === "settings" && course && <Settings key={`${course}:${group}`} course={course} group={group} perform={perform} busy={busy} />}
  </main>;
}

function Settings({ course, group, perform, busy }) {
  const modeState = usePolling(`${coursePath(course)}/settings${group ? `?group_id=${encodeURIComponent(group)}` : ""}`);
  const modeLocked = modeState.data?.mode_locked;
  const [config,setConfig] = useState(null), [random,setRandom] = useState(false), [deadlines,setDeadlines] = useState({}), [error,setError] = useState("");
  useEffect(() => { let alive=true; queueRequest(`${coursePath(course)}/settings`).then(data => { if(alive) {setConfig(data);setRandom(Boolean(data.queue.random));setDeadlines(data.queue.deadlines || {});} }).catch(err=>setError(err.message));return()=>{alive=false;}; },[course]);
  if(error) return <p role="alert">{error}</p>;
  if(!config) return <p role="status">Загружаются настройки…</p>;
  const patch = (key,value,remove=false) => setDeadlines(old => {const next={...old};if(remove) delete next[key];else next[key]=value;return next;});
  return <form onSubmit={e => {e.preventDefault();perform(()=>queueRequest(`${coursePath(course)}/settings`,{method:"PUT",body:{random,deadlines}}).then(() => modeState.refresh()));}}>
    <h2>Дедлайны и порядок</h2>
    {modeState.error && <p role="alert">{modeState.error.message}</p>}
    <label className="queue-checkbox"><input type="checkbox" checked={modeLocked ? true : random} disabled={modeLocked || modeLocked == null || busy} onChange={e=>setRandom(e.target.checked)}/> Случайный порядок</label>
    {modeLocked && <p className="queue-notice">Есть непрочитанный дедлайн без ручного значения: случайный режим обязателен. После восстановления данных автоматически включится приоритет, если случайный режим не выбран вручную.</p>}
    <p>«Без дедлайна» означает отсутствие срока по правилам работы. «Из таблицы» требует читаемую дату; пустая ячейка не считается отсутствием срока.</p>
    <div className="queue-settings">{config.labs.map(lab => <fieldset key={lab.key}><legend>{lab.title}</legend>
      <label>Источник<select value={!(lab.key in deadlines) ? "sheet" : deadlines[lab.key] === null ? "none" : "manual"} onChange={e => patch(lab.key,e.target.value === "none" ? null : "",e.target.value === "sheet")}><option value="sheet">Из таблицы</option><option value="none">Без дедлайна</option><option value="manual">Вручную</option></select></label>
      {lab.key in deadlines && deadlines[lab.key] !== null && <label>Дата<input required placeholder="ГГГГ-ММ-ДД" value={deadlines[lab.key]} onChange={e => patch(lab.key,e.target.value)}/></label>}
    </fieldset>)}</div><button className="primary" disabled={busy}>Сохранить настройки</button>
  </form>;
}

function Schedule({ course, group, sessions, perform, busy, version, onSaved }) {
  const [start,setStart]=useState(""), [end,setEnd]=useState(""), [teacher,setTeacher]=useState("main");
  const [source,setSource]=useState({source:"manual",university:""}), [error,setError]=useState("");
  const [edit,setEdit]=useState(null), [moveStart,setMoveStart]=useState(""), [moveEnd,setMoveEnd]=useState("");
  const path = queueGroupPath(course,group,true);
  useEffect(()=>{let alive=true;if(course)queueRequest(`${coursePath(course)}/settings`).then(data=>{if(alive)setSource(data.queue.schedule?.[group] || {source:"manual",university:""});}).catch(err=>setError(err.message));return()=>{alive=false;};},[course,group,version]);
  const field=(key,value)=>setSource(old=>({...old,[key]:value}));
  const iso=value=>new Date(value).toISOString();
  return <>
    <h2>Расписание преподавателя</h2>
    <p>Все группы и предметы; время отображается в часовом поясе занятия. Ввод дат ниже использует часовой пояс браузера ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
    <div className="queue-table-wrap"><table className="queue-table"><thead><tr><th>Предмет / группа</th><th>Начало</th><th>Окончание</th><th>Преподаватель / источник</th><th>Действия</th></tr></thead><tbody>
      {[...sessions].sort((a,b)=>a.starts_at-b.starts_at).map(s=><tr key={s.session_id}><td>{s.course_title}<br/>{s.group_id}</td><td>{displayDate(s.starts_at,s.timezone)}</td><td>{displayDate(s.ends_at,s.timezone)}{s.enrollment_status==="cancelled" && " · отменено"}</td><td>{s.teacher_key}<br/>{s.source_kind === "university" ? "Вуз" : "Вручную"}</td><td><div className="queue-actions"><button disabled={busy || s.enrollment_status==="cancelled"} onClick={()=>{setEdit(s);setMoveStart("");setMoveEnd("");}}>Перенести</button><button disabled={busy || s.enrollment_status==="cancelled"} onClick={()=>perform(()=>queueRequest(`${queueGroupPath(s.course_id,s.group_id,true)}/sessions/${encodeURIComponent(s.session_id)}`,{method:"PATCH",body:{cancel:true}}))}>Отменить</button></div></td></tr>)}
    </tbody></table></div>
    {edit && <form className="queue-notice" onSubmit={e=>{e.preventDefault();perform(async()=>{await queueRequest(`${queueGroupPath(edit.course_id,edit.group_id,true)}/sessions/${encodeURIComponent(edit.session_id)}`,{method:"PATCH",body:{starts_at:iso(moveStart),ends_at:iso(moveEnd)}});setEdit(null);});}}><h3>Перенос занятия · {edit.group_id}</h3><div className="queue-toolbar"><label>Новое начало<input type="datetime-local" required value={moveStart} onChange={e=>setMoveStart(e.target.value)}/></label><label>Новое окончание<input type="datetime-local" required value={moveEnd} onChange={e=>setMoveEnd(e.target.value)}/></label><button disabled={busy}>Сохранить перенос</button><button type="button" onClick={()=>setEdit(null)}>Закрыть</button></div></form>}
    {course && group && <>
      <form onSubmit={e=>{e.preventDefault();perform(()=>queueRequest(`${path}/sessions`,{method:"POST",body:{session_id:crypto.randomUUID(),teacher_key:teacher,starts_at:iso(start),ends_at:iso(end)}}));}}>
        <h3>Добавить занятие · {group}</h3><div className="queue-toolbar"><label>Начало<input type="datetime-local" required value={start} onChange={e=>setStart(e.target.value)}/></label><label>Окончание<input type="datetime-local" required value={end} onChange={e=>setEnd(e.target.value)}/></label><label>Ключ преподавателя<input required value={teacher} onChange={e=>setTeacher(e.target.value)}/></label><button disabled={busy}>Добавить</button></div>
      </form>
      <form onSubmit={e=>{e.preventDefault();perform(async()=>{await queueRequest(`${path}/schedule`,{method:"PUT",body:{config:source}});await queueRequest(`${path}/schedule/refresh`,{method:"POST"});onSaved();});}}>
        <h3>Источник расписания · {group}</h3>{error && <p role="alert">{error}</p>}<div className="queue-settings">
          <label>Вуз<input value={source.university || ""} onChange={e=>field("university",e.target.value)} placeholder="Название вуза"/></label>
          <label>Источник<select value={source.source} onChange={e=>{field("source",e.target.value);setError("");}}><option value="manual">Вручную</option><option value="suai">ГУАП</option><option value="import">Импорт другого вуза</option></select></label>
          {source.source==="suai" && <>
            <label>ID группы на сайте<input required value={source.group_id || ""} onChange={e=>field("group_id",e.target.value)}/></label>
            <label>Точное название предмета<input required value={source.subject || ""} onChange={e=>field("subject",e.target.value)}/></label>
            <label>Вид занятия (например ЛР)<input value={source.kind || ""} onChange={e=>field("kind",e.target.value)}/></label>
            <label>ID преподавателя (необязательно)<input value={source.teacher_id || ""} onChange={e=>field("teacher_id",e.target.value)}/></label>
            <label>Ключ преподавателя<input value={source.teacher_key || "main"} onChange={e=>field("teacher_key",e.target.value)}/></label>
            <label>Понедельник нечётной недели<input type="date" required value={source.week_anchor || ""} onChange={e=>field("week_anchor",e.target.value)}/></label>
            <label>Конец семестра<input type="date" value={source.semester_end || ""} onChange={e=>field("semester_end",e.target.value)}/></label>
          </>}
        </div>
        {source.source==="import" && <label>Занятия JSON (key, starts_at, ends_at, teacher_key)<textarea rows={8} defaultValue={JSON.stringify(source.lessons || [],null,2)} key={`${course}:${group}:${version}:${source.source}`} onChange={e=>{try{const rows=JSON.parse(e.target.value);if(!Array.isArray(rows))throw Error();field("lessons",rows);setError("");}catch{setError("Нужен корректный JSON-массив занятий");}}}/></label>}
        <button disabled={busy || Boolean(error)}>Сохранить и обновить расписание</button>
      </form>
    </>}
  </>;
}
