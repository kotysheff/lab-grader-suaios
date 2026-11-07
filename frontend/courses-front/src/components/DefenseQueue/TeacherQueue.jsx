import { queueError, q, useQueueLanguage, QueueLanguage } from "./locale";
import { useEffect, useState } from "react";
import { fetchCourses, fetchGroups, queueGroupPath, queueRequest } from "../../api";
import { usePolling } from "./usePolling";
import { entryLabel } from "./state";
import "./queue.css";
import { queueAppearance } from "./appearance";
import { useRowMotion } from "./useRowMotion";
const coursePath = id => `/admin/courses/${encodeURIComponent(id)}/queue`;
const eventNames = {
  called: "Вызван",
  defended: "Защитил",
  failed: "Не защитил",
  no_show: "Не явился",
  withdrawn: "Исключён",
  added_to_tail: "Добавлен в конец",
  roster_frozen: "Состав зафиксирован",
  schedule_changed: "Занятие перенесено",
  enrollment_closed: "Запись закрыта",
  enrollment_opened: "Запись открыта",
  cancelled: "Занятие отменено",
  sheet_defended: "Защита подтверждена таблицей",
  session_finished: "Ожидание завершено"
};
export function TeacherQueue({
  initialCourse = ""
}) {
  const { displayDate } = useQueueLanguage();
  const [courses, setCourses] = useState([]),
    [course, setCourse] = useState(initialCourse);
  const [groups, setGroups] = useState([]),
    [group, setGroup] = useState("");
  const [sessionId, setSessionId] = useState(""),
    [tab, setTab] = useState("queue");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const sessions = usePolling("/admin/queue/sessions");
  const path = course && group ? queueGroupPath(course, group, true) : null;
  const roster = usePolling(path && sessionId ? `${path}?session_id=${encodeURIComponent(sessionId)}` : null);
  const [settingsVersion, setSettingsVersion] = useState(0);
  const [manualCandidate, setManualCandidate] = useState("");
  useEffect(() => {
    let alive = true;
    fetchCourses("all").then(rows => {
      if (alive) {
        setCourses(rows);
        setCourse(value => value || rows[0]?.id || "");
      }
    }).catch(err => setError(err));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    let alive = true;
    setGroups([]);
    setGroup("");
    setSessionId("");
    if (course) fetchGroups(course).then(rows => {
      if (alive) {
        setGroups(rows);
        setGroup(rows[0] || "");
      }
    }).catch(err => {
      if (alive) setError(err);
    });
    return () => {
      alive = false;
    };
  }, [course]);
  const filtered = (sessions.data || []).filter(s => s.course_id === course && s.group_id === group).sort((a, b) => a.starts_at - b.starts_at);
  useEffect(() => {
    if (!filtered.some(s => s.session_id === sessionId)) {
      const now = Date.now() / 1000;
      setSessionId((filtered.find(s => s.starts_at <= now && s.ends_at > now && s.enrollment_status !== "cancelled") || filtered.find(s => s.starts_at > now && s.enrollment_status !== "cancelled") || filtered.at(-1))?.session_id || "");
    }
  }, [course, group, sessions.data, sessionId]);
  async function perform(task) {
    setBusy(true);
    setError("");
    try {
      await task();
      roster.refresh();
      sessions.refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const action = payload => perform(() => queueRequest(`${path}/actions`, {
    method: "POST",
    body: {
      session_id: sessionId,
      request_id: crypto.randomUUID(),
      ...payload
    }
  }));
  const data = roster.data;
  const rowContainer = useRowMotion(`${sessionId}:${tab}:${data?.entries.map(row => row.candidate_id).join(",") || ""}`);
  return <main className="queue-surface queue-admin" style={queueAppearance}>
    <a className="queue-back" href="/admin/courses">{q("← Предметы")}</a>
    <QueueLanguage />
    <header className="queue-page-heading"><h1>{q("Защита лабораторных")}</h1>
    <p className="queue-muted">{q("Полный состав занятия, результаты и расписание.")}</p></header>
    <div className="queue-toolbar queue-filters">
      <label>{q("Предмет")}<select disabled={busy} value={course} onChange={e => setCourse(e.target.value)}>{courses.map(c => <option key={c.id} value={c.id}>{c.name || c.id}</option>)}</select></label>
      <label>{q("Группа")}<select disabled={busy} value={group} onChange={e => {
          setGroup(e.target.value);
          setSessionId("");
        }}>{groups.map(g => <option key={g}>{g}</option>)}</select></label>
      <label>{q("Занятие")}<select disabled={busy} value={sessionId} onChange={e => setSessionId(e.target.value)}><option value="">{q("Выберите занятие")}</option>{filtered.map(s => <option key={s.session_id} value={s.session_id}>{displayDate(s.starts_at, s.timezone)}{s.enrollment_status === "cancelled" ? q(" · отменено") : ""}</option>)}</select></label>
    </div>
    <nav className="queue-tabs" aria-label={q("Разделы панели")}>{[["queue", q("Очередь")], ["schedule", q("Расписание")], ["settings", q("Дедлайны и порядок")]].map(([key, label]) => <button key={key} disabled={busy} aria-current={tab === key ? "page" : undefined} className={tab === key ? "primary" : ""} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {(error || sessions.error || roster.error) && <p role="alert" className="queue-notice queue-error">{queueError(error || sessions.error || roster.error)} <button onClick={() => {
        roster.refresh();
        sessions.refresh();
      }}>{q("Повторить")}</button></p>}
    <div className={`queue-feedback ${busy ? "is-saving" : ""}`} role="status" aria-live="polite" aria-atomic="true"><span className="queue-spinner" aria-hidden="true" />{busy ? q("Сохраняется…") : ""}</div>
    <div className="queue-content" key={tab} aria-busy={busy}>
    {tab === "queue" && <>
      {!sessionId && <p className="queue-notice">{q("Назначьте занятие во вкладке «Расписание».")}</p>}
      {sessionId && !data && !roster.error && <p role="status">{q("Загружается очередь…")}</p>}
      {data && <>
        <div className="queue-session-heading"><h2>{displayDate(data.session.starts_at, data.session.timezone)} <span className="queue-group-badge">{group}</span></h2>
        <p>{data.mode === "random" ? q("Случайный порядок") : q("Приоритет по дедлайнам, от −1")}. {data.attendance_open ? q("Студенты могут менять посещение до начала пары.") : q("Состав зафиксирован; изменения доступны преподавателю.")}</p></div>
        {data.stale && <p className="queue-notice">{q("Таблица недоступна. Показан сохранённый состав, обновление допуска ожидается.")}</p>}
        {Date.now() / 1000 < data.session.starts_at && data.session.enrollment_status !== "cancelled" && <button disabled={busy} onClick={() => action({
            action: data.session.enrollment_status === "closed" ? "open_enrollment" : "close_enrollment"
          })}>{data.session.enrollment_status === "closed" ? q("Открыть запись") : q("Закрыть запись досрочно")}</button>}
        <dl className="queue-summary">{[["called", q("Сдают сейчас")], ["waiting", q("Ждут")], ["defended", q("Сдано")], ["failed", q("Неудачных попыток")], ["no_show", q("Неявок")]].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{data.stats[key]}</dd></div>)}</dl>
        <div className="queue-call-toolbar"><button className="primary queue-call-button" disabled={busy || Date.now() / 1000 < data.session.starts_at || !data.next_entry_id} onClick={() => action({
              action: "call_next"
            })}>{q("Вызвать следующего")}</button><span className="queue-muted">{data.current_entry_ids?.length ? q("Можно вызвать ещё одного студента; результат отмечается отдельно для каждого") : data.next_entry_id ? q("Следующий студент выделен в списке") : q("Нет ожидающих студентов")}</span></div>
        <div className="queue-table-wrap" role="region" aria-label={q("Список сдающих")} tabIndex={0}><table className="queue-table queue-roster-table"><colgroup><col className="queue-col-position" /><col className="queue-col-student" /><col className="queue-col-lab" /><col className="queue-col-date" /><col className="queue-col-status" /><col className="queue-col-actions" /></colgroup><caption className="queue-sr-only">{q("Все участники и результаты выбранного занятия")}</caption><thead><tr><th scope="col" aria-label={q("Позиция")}>№</th><th>{q("Студент / GitHub")}</th><th>{q("Работа")}</th><th>{q("Допущен")}</th><th>{q("Статус")}</th><th>{q("Действия")}</th></tr></thead><tbody ref={rowContainer}>
          {data.entries.map((row, index) => {
                  const current = (data.current_entry_ids || [data.current_entry_id]).includes(row.attempt?.entry_id),
                    next = row.attempt?.entry_id === data.next_entry_id;
                  const active = ["waiting", "called"].includes(row.attempt?.status);
                  return <tr key={row.candidate_id} data-queue-row={row.candidate_id} className={`${current ? "current" : next ? "next" : row.state} ${row.attempt?.is_repeat ? "repeat" : ""}`}>
              <td data-label={q("Позиция")}>{active ? index + 1 : row.position ?? "—"}</td><td data-label={q("Студент / GitHub")}><strong>{row.full_name}</strong><br /><a href={`https://github.com/${encodeURIComponent(row.github)}`} target="_blank" rel="noreferrer">{row.github}</a></td><td data-label={q("Работа")}>{row.lab_key}{row.priority != null && <small><br />{q("Приоритет")} {row.priority}</small>}</td><td data-label={q("Допущен")}>{displayDate(row.qualified_at, data.session.timezone)}</td><td data-label={q("Статус")}><span className={`queue-status ${current ? "is-current" : next ? "is-next" : ""}`}>{q(entryLabel(row, {
                          current: data.current_entry_ids || [data.current_entry_id],
                          next: data.next_entry_id
                        }))}</span></td>
              <td data-label={q("Действия")}><div className="queue-row-actions">{!current && <span className="queue-action-hint">{q("Результат после вызова")}</span>}{[["defended", q("Сдал")], ["failed", q("Не сдал")], ["no_show", q("Не пришёл")]].map(([outcome, label]) => <button key={outcome} className={`queue-result ${outcome}`} data-visible={current} aria-hidden={!current} tabIndex={current ? 0 : -1} disabled={busy || !current} onClick={() => action({
                          action: "result",
                          entry_id: row.attempt.entry_id,
                          outcome
                        })}>{label}</button>)}
                {active ? <button className="queue-manage" disabled={busy} onClick={() => action({
                          action: "withdraw",
                          entry_id: row.attempt.entry_id
                        })}>{q("Убрать")}</button> : <button className="queue-manage" disabled={busy || Date.now() / 1000 >= data.session.ends_at || data.session.enrollment_status === "cancelled"} onClick={() => action({
                          action: "add_tail",
                          candidate_id: row.candidate_id
                        })}>{q("В конец")}</button>}
              </div></td></tr>;
                })}
        </tbody></table></div>
        {!data.entries.length && <p>{q("Участников пока нет.")}</p>}
        <details><summary>{q("Добавить допущенного студента в конец")}</summary>
          <form className="queue-toolbar" onSubmit={e => {
              e.preventDefault();
              action({
                action: "add_tail",
                candidate_id: Number(manualCandidate)
              });
            }}>
            <label>{q("Студент")}<select required value={manualCandidate} onChange={e => setManualCandidate(e.target.value)}><option value="">{q("Выберите студента")}</option>{(data.available_candidates || []).map(row => <option key={row.candidate_id} value={row.candidate_id}>{row.full_name}{q("· работа")} {row.lab_key}</option>)}</select></label>
            <button disabled={busy || !data.available_candidates?.some(row => String(row.candidate_id) === manualCandidate) || Date.now() / 1000 >= data.session.ends_at || data.session.enrollment_status === "cancelled"}>{q("Добавить в конец")}</button>
          </form>
        </details>
        <details><summary>{q("История и попытки")}</summary>
          <ul className="queue-history">{data.history.map(e => <li key={e.event_id}>{displayDate(e.occurred_at, data.session.timezone)} · {q(eventNames[e.kind] || e.kind)}{e.full_name ? q(" · {{v0}} · работа {{v1}}", {
                  v0: e.full_name,
                  v1: e.lab_key
                }) : ""}{e.entry_id ? q(" · попытка {{v0}}", {
                  v0: e.entry_id
                }) : ""}</li>)}</ul>
          <p>{q("Сверка с таблицей:")} {data.reconciliation?.done_at ? displayDate(data.reconciliation.done_at, data.session.timezone) : data.reconciliation?.error ? q("ожидается повтор после ошибки чтения") : q("через 10 минут после окончания")}.</p>
        </details>
      </>}
    </>}
    {tab === "schedule" && <Schedule course={course} group={group} sessions={sessions.data || []} perform={perform} busy={busy} version={settingsVersion} onSaved={() => setSettingsVersion(v => v + 1)} />}
    {tab === "settings" && course && <Settings key={`${course}:${group}`} course={course} group={group} perform={perform} busy={busy} />}
    </div>
  </main>;
}
function Settings({
  course,
  group,
  perform,
  busy
}) {
  useQueueLanguage();
  const modeState = usePolling(`${coursePath(course)}/settings${group ? `?group_id=${encodeURIComponent(group)}` : ""}`);
  const modeLocked = modeState.data?.mode_locked;
  const [config, setConfig] = useState(null),
    [random, setRandom] = useState(false),
    [deadlines, setDeadlines] = useState({}),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    queueRequest(`${coursePath(course)}/settings`).then(data => {
      if (alive) {
        setConfig(data);
        setRandom(Boolean(data.queue.random));
        setDeadlines(data.queue.deadlines || {});
      }
    }).catch(err => setError(err));
    return () => {
      alive = false;
    };
  }, [course]);
  if (error) return <p role="alert">{queueError(error)}</p>;
  if (!config) return <p role="status">{q("Загружаются настройки…")}</p>;
  const patch = (key, value, remove = false) => setDeadlines(old => {
    const next = {
      ...old
    };
    if (remove) delete next[key];else next[key] = value;
    return next;
  });
  return <form onSubmit={e => {
    e.preventDefault();
    perform(() => queueRequest(`${coursePath(course)}/settings`, {
      method: "PUT",
      body: {
        random,
        deadlines
      }
    }).then(() => modeState.refresh()));
  }}>
    <h2>{q("Дедлайны и порядок")}</h2>
    {modeState.error && <p role="alert">{queueError(modeState.error)}</p>}
    <label className="queue-checkbox"><input type="checkbox" checked={modeLocked ? true : random} disabled={modeLocked || modeLocked == null || busy} onChange={e => setRandom(e.target.checked)} />{q("Случайный порядок")}</label>
    {modeLocked && <p className="queue-notice">{q("Есть непрочитанный дедлайн без ручного значения: случайный режим обязателен. После восстановления данных автоматически включится приоритет, если случайный режим не выбран вручную.")}</p>}
    <p>{q("«Без дедлайна» означает отсутствие срока по правилам работы. «Из таблицы» требует читаемую дату; пустая ячейка не считается отсутствием срока.")}</p>
    <div className="queue-settings">{config.labs.map(lab => <fieldset key={lab.key}><legend>{lab.title}</legend>
      <label>{q("Источник")}<select value={!(lab.key in deadlines) ? "sheet" : deadlines[lab.key] === null ? "none" : "manual"} onChange={e => patch(lab.key, e.target.value === "none" ? null : "", e.target.value === "sheet")}><option value="sheet">{q("Из таблицы")}</option><option value="none">{q("Без дедлайна")}</option><option value="manual">{q("Вручную")}</option></select></label>
      {lab.key in deadlines && deadlines[lab.key] !== null && <label>{q("Дата")}<input required placeholder={q("ГГГГ-ММ-ДД")} value={deadlines[lab.key]} onChange={e => patch(lab.key, e.target.value)} /></label>}
    </fieldset>)}</div><button className="primary" disabled={busy}>{q("Сохранить настройки")}</button>
  </form>;
}
function Schedule({
  course,
  group,
  sessions,
  perform,
  busy,
  version,
  onSaved
}) {
  const { displayDate } = useQueueLanguage();
  const [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [teacher, setTeacher] = useState("main");
  const [source, setSource] = useState({
      source: "manual",
      university: ""
    }),
    [error, setError] = useState("");
  const [edit, setEdit] = useState(null),
    [moveStart, setMoveStart] = useState(""),
    [moveEnd, setMoveEnd] = useState("");
  const path = queueGroupPath(course, group, true);
  useEffect(() => {
    let alive = true;
    if (course) queueRequest(`${coursePath(course)}/settings`).then(data => {
      if (alive) setSource(data.queue.schedule?.[group] || {
        source: "manual",
        university: ""
      });
    }).catch(err => setError(err));
    return () => {
      alive = false;
    };
  }, [course, group, version]);
  const field = (key, value) => setSource(old => ({
    ...old,
    [key]: value
  }));
  const iso = value => new Date(value).toISOString();
  return <>
    <h2>{q("Расписание преподавателя")}</h2>
    <p>{q("Все группы и предметы; время отображается в часовом поясе занятия. Ввод дат ниже использует часовой пояс браузера (")} {Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
    <div className="queue-table-wrap"><table className="queue-table"><thead><tr><th>{q("Предмет / группа")}</th><th>{q("Начало")}</th><th>{q("Окончание")}</th><th>{q("Преподаватель / источник")}</th><th>{q("Действия")}</th></tr></thead><tbody>
      {[...sessions].sort((a, b) => a.starts_at - b.starts_at).map(s => <tr key={s.session_id}><td>{s.course_title}{s.university && <small><br />{s.university}</small>}<br />{s.group_id}</td><td>{displayDate(s.starts_at, s.timezone)}</td><td>{displayDate(s.ends_at, s.timezone)}{s.enrollment_status === "cancelled" && q(" · отменено")}</td><td>{s.teacher_key}<br />{s.source_kind === "university" ? q("Вуз") : q("Вручную")}</td><td><div className="queue-actions"><button disabled={busy || s.enrollment_status === "cancelled"} onClick={() => {
                  setEdit(s);
                  setMoveStart("");
                  setMoveEnd("");
                }}>{q("Перенести")}</button><button disabled={busy || s.enrollment_status === "cancelled"} onClick={() => perform(() => queueRequest(`${queueGroupPath(s.course_id, s.group_id, true)}/sessions/${encodeURIComponent(s.session_id)}`, {
                  method: "PATCH",
                  body: {
                    cancel: true
                  }
                }))}>{q("Отменить")}</button></div></td></tr>)}
    </tbody></table></div>
    {edit && <form className="queue-notice" onSubmit={e => {
      e.preventDefault();
      perform(async () => {
        await queueRequest(`${queueGroupPath(edit.course_id, edit.group_id, true)}/sessions/${encodeURIComponent(edit.session_id)}`, {
          method: "PATCH",
          body: {
            starts_at: iso(moveStart),
            ends_at: iso(moveEnd)
          }
        });
        setEdit(null);
      });
    }}><h3>{q("Перенос занятия ·")} {edit.group_id}</h3><div className="queue-toolbar"><label>{q("Новое начало")}<input type="datetime-local" required value={moveStart} onChange={e => setMoveStart(e.target.value)} /></label><label>{q("Новое окончание")}<input type="datetime-local" required value={moveEnd} onChange={e => setMoveEnd(e.target.value)} /></label><button disabled={busy}>{q("Сохранить перенос")}</button><button type="button" onClick={() => setEdit(null)}>{q("Закрыть")}</button></div></form>}
    {course && group && <>
      <form onSubmit={e => {
        e.preventDefault();
        perform(() => queueRequest(`${path}/sessions`, {
          method: "POST",
          body: {
            session_id: crypto.randomUUID(),
            teacher_key: teacher,
            starts_at: iso(start),
            ends_at: iso(end)
          }
        }));
      }}>
        <h3>{q("Добавить занятие ·")} {group}</h3><div className="queue-toolbar"><label>{q("Начало")}<input type="datetime-local" required value={start} onChange={e => setStart(e.target.value)} /></label><label>{q("Окончание")}<input type="datetime-local" required value={end} onChange={e => setEnd(e.target.value)} /></label><label>{q("Ключ преподавателя")}<input required value={teacher} onChange={e => setTeacher(e.target.value)} /></label><button disabled={busy}>{q("Добавить")}</button></div>
      </form>
      <form onSubmit={e => {
        e.preventDefault();
        perform(async () => {
          await queueRequest(`${path}/schedule`, {
            method: "PUT",
            body: {
              config: source
            }
          });
          await queueRequest(`${path}/schedule/refresh`, {
            method: "POST"
          });
          onSaved();
        });
      }}>
        <h3>{q("Источник расписания ·")} {group}</h3>{error && <p role="alert">{queueError(error)}</p>}<div className="queue-settings">
          <label>{q("Вуз")}<input value={source.university || ""} onChange={e => field("university", e.target.value)} placeholder={q("Название вуза")} /></label>
          <label>{q("Источник")}<select value={source.source} onChange={e => {
              field("source", e.target.value);
              setError("");
            }}><option value="manual">{q("Вручную")}</option><option value="suai">{q("ГУАП")}</option><option value="import">{q("Импорт другого вуза")}</option></select></label>
          {source.source === "suai" && <>
            <label>{q("ID группы на сайте")}<input required value={source.group_id || ""} onChange={e => field("group_id", e.target.value)} /></label>
            <label>{q("Точное название предмета")}<input required value={source.subject || ""} onChange={e => field("subject", e.target.value)} /></label>
            <label>{q("Вид занятия (например ЛР)")}<input value={source.kind || ""} onChange={e => field("kind", e.target.value)} /></label>
            <label>{q("ID преподавателя (необязательно)")}<input value={source.teacher_id || ""} onChange={e => field("teacher_id", e.target.value)} /></label>
            <label>{q("Ключ преподавателя")}<input value={source.teacher_key || "main"} onChange={e => field("teacher_key", e.target.value)} /></label>
            <label>{q("Понедельник нечётной недели")}<input type="date" required value={source.week_anchor || ""} onChange={e => field("week_anchor", e.target.value)} /></label>
            <label>{q("Конец семестра")}<input type="date" value={source.semester_end || ""} onChange={e => field("semester_end", e.target.value)} /></label>
          </>}
        </div>
        {source.source === "import" && <label>{q("Занятия JSON (key, starts_at, ends_at, teacher_key)")}<textarea rows={8} defaultValue={JSON.stringify(source.lessons || [], null, 2)} key={`${course}:${group}:${version}:${source.source}`} onChange={e => {
            try {
              const rows = JSON.parse(e.target.value);
              if (!Array.isArray(rows)) throw Error();
              field("lessons", rows);
              setError("");
            } catch {
              setError(q("Нужен корректный JSON-массив занятий"));
            }
          }} /></label>}
        <button disabled={busy || Boolean(error)}>{q("Сохранить и обновить расписание")}</button>
      </form>
    </>}
  </>;
}
