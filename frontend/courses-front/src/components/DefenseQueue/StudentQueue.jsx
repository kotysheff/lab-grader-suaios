import { Hint } from "./Hint";
import { queueError, q, useQueueLanguage } from "./locale";
import { useState } from "react";
import { queueGroupPath, queueRequest } from "../../api";
import { ownEntry, canIdentify, entryLabel } from "./state";
import { usePolling } from "./usePolling";
import "./queue.css";
import { queueAppearance } from "./appearance";
export function StudentQueue({
  courseId,
  groupId,
  identity,
  checking,
  labId,
  refreshToken
}) {
  const { displayDate } = useQueueLanguage();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const path = queueGroupPath(courseId, groupId);
  const {
    data,
    error,
    refresh
  } = usePolling(`${path}${checking ? `?preview_lab=${encodeURIComponent(labId)}` : ""}`, refreshToken);
  const me = ownEntry(data?.entries, identity.github);
  const displayRows = [...(data?.entries || [])];
  if (checking && !me && identity.github) {
    const preview = {
      candidate_id: "preview",
      preview: true
    };
    const index = displayRows.findIndex(row => row.will_attend && row.position >= data?.preview?.position);
    displayRows.splice(index < 0 ? displayRows.length : index, 0, preview);
  }
  async function choose(willAttend) {
    setSaving(true);
    setSaveError("");
    try {
      await queueRequest(`${path}/attendance`, {
        method: "POST",
        body: {
          ...identity,
          session_id: data.session.session_id,
          will_attend: willAttend
        }
      });
      refresh();
    } catch (err) {
      setSaveError(err);
      if (err.status === 409) refresh();
    } finally {
      setSaving(false);
    }
  }
  if (error?.status === 404) return <p className="queue-muted">{q("Для этого предмета очередь пока не включена.")}</p>;
  return <section className="queue-surface queue-student" style={queueAppearance} aria-label={q("Список на занятие")}>
    <h2>{q("Ближайшее занятие")}</h2>
    {data?.session ? <p><strong>{displayDate(data.session.starts_at, data.session.timezone)}</strong><br /><small>{q("Группа")} {groupId} · {data.mode === "random" ? q("Случайный порядок") : q("Приоритет по дедлайнам, от −1")}</small></p> : data ? <p>{q("Будущее занятие пока не назначено. Список допущенных работ доступен ниже.")}</p> : !error && <p role="status">{q("Загружается список…")}</p>}
    {error && <div className="queue-notice queue-error" role="alert">{queueError(error)} <button onClick={refresh}>{q("Повторить")}</button></div>}
    {data?.stale && <p className="queue-notice">{q("Таблица временно недоступна. Показан сохранённый список; изменение посещения появится после обновления.")}</p>}
    {checking && <p className="queue-notice" role="status">{q("Работа проверяется. Предварительная позиция не резервирует место.")}</p>}
    {me && <div className="queue-notice queue-attendance">
      <strong><Hint text="По умолчанию участие не подтверждено. «Да» включает в список сдающих. Ответ можно менять до начала занятия. «Нет» сохраняет допуск к работе, но исключает из вызова на это занятие.">{q("Придёте сдавать на это занятие?")}</Hint></strong>
      <p className="queue-attendance-hint" aria-live="polite">{!me.answered ? q("По умолчанию вы не включены в состав приходящих.") : me.will_attend ? q("Приход подтверждён. Ответ можно изменить до начала занятия.") : q("Вы отметили, что не придёте. Ответ можно изменить до начала занятия.")}</p>
      <div className="queue-actions">
        <button aria-pressed={me.will_attend} disabled={!data.attendance_open || data.stale || saving || checking || !canIdentify(identity)} onClick={() => choose(true)}>{q("Да, я приду")}</button>
        <button aria-pressed={!me.will_attend} disabled={!data.attendance_open || data.stale || saving || checking || !canIdentify(identity)} onClick={() => choose(false)}>{q("Нет, не приду")}</button>
      </div>
      {!data.attendance_open && <p>{q("Изменение посещения недоступно для этого занятия.")}</p>}
      {!canIdentify(identity) && <p>{q("Заполните ФИО и GitHub в форме выше.")}</p>}
    </div>}
    <ol className="queue-list">
      {displayRows.map(row => row.preview ? <li key="preview" className="queue-row queue-preview">
        <span className="queue-rank">{data?.preview?.position ?? "?"}</span><div><strong>{identity.surname} {identity.name}</strong><small>{labId}{q("· Предварительная позиция")}</small></div><small>{q("Проверка…")}</small>
      </li> : <li key={row.candidate_id} className={`queue-row ${row.state} ${row.candidate_id === me?.candidate_id ? "mine" : ""}`}>
        <span className="queue-rank">{row.position ?? "—"}</span>
        <div><strong className="queue-name">{row.full_name}</strong><small>{row.lab_title || q("Работа {{v0}}", {
              v0: row.lab_key
            })} · <a href={`https://github.com/${encodeURIComponent(row.github)}`} target="_blank" rel="noreferrer">{row.github}</a></small></div>
        <small>{q(entryLabel(row))}</small>
      </li>)}
    </ol>
    {data && !data.entries?.length && !checking && <p className="queue-muted">{q("Пока нет допущенных участников. После успешной проверки работа появится здесь.")}</p>}
    {data && !me && !checking && <p className="queue-muted">{q("Для указанного GitHub допущенная работа пока не найдена. Успешно зарегистрируйте первую незащищённую лабораторную.")}</p>}
    {saveError && <p role="alert" className="queue-notice queue-error">{queueError(saveError)}</p>}
    <div className={`queue-feedback ${saving ? "is-saving" : ""}`} role="status" aria-live="polite"><span className="queue-spinner" aria-hidden="true" />{saving ? q("Сохраняется ответ…") : ""}</div>
    <small>{q("Ответ можно изменить до начала пары. Для возвращения к списку новая проверка не требуется.")}</small>
  </section>;
}
