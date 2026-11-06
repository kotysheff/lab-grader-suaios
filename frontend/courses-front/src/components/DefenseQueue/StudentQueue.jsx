import { useState } from "react";
import { queueGroupPath, queueRequest } from "../../api";
import { ownEntry, canIdentify, displayDate, entryLabel } from "./state";
import { usePolling } from "./usePolling";
import "./queue.css";
import { queueAppearance } from "./appearance";

export function StudentQueue({ courseId, groupId, identity, checking, labId, refreshToken }) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const path = queueGroupPath(courseId, groupId);
  const { data, error, refresh } = usePolling(`${path}${checking ? `?preview_lab=${encodeURIComponent(labId)}` : ""}`, refreshToken);
  const me = ownEntry(data?.entries, identity.github);
  const displayRows = [...(data?.entries || [])];
  if (checking && !me && identity.github) {
    const preview = { candidate_id: "preview", preview: true };
    const index = displayRows.findIndex(row => row.will_attend && row.position >= data?.preview?.position);
    displayRows.splice(index < 0 ? displayRows.length : index, 0, preview);
  }
  async function choose(willAttend) {
    setSaving(true); setSaveError("");
    try {
      await queueRequest(`${path}/attendance`, { method: "POST", body: { ...identity, session_id: data.session.session_id, will_attend: willAttend } });
      refresh();
    } catch (err) { setSaveError(err.message); if (err.status === 409) refresh(); }
    finally { setSaving(false); }
  }
  if (error?.status === 404) return <p className="queue-muted">Для этого предмета очередь пока не включена.</p>;
  return <section className="queue-surface" style={queueAppearance} aria-label="Список на занятие">
    <h2>Ближайшее занятие</h2>
    {data?.session ? <p><strong>{displayDate(data.session.starts_at, data.session.timezone)}</strong><br /><small>Группа {groupId} · {data.mode === "random" ? "Случайный порядок" : "Приоритет по дедлайнам, от −1"}</small></p> : data ? <p>{data.message}</p> : !error && <p role="status">Загружается список…</p>}
    {error && <div className="queue-notice queue-error" role="alert">{error.message} <button onClick={refresh}>Повторить</button></div>}
    {data?.stale && <p className="queue-notice">Таблица временно недоступна. Показан сохранённый список; изменение посещения появится после обновления.</p>}
    {checking && <p className="queue-notice" role="status">Работа проверяется. Предварительная позиция не резервирует место.</p>}
    <ol className="queue-list">
      {displayRows.map(row => row.preview ? <li key="preview" className="queue-row queue-preview">
        <span className="queue-rank">{data?.preview?.position ?? "?"}</span><div><strong>{identity.surname} {identity.name}</strong><small>{labId} · Предварительная позиция</small></div><small>Проверка…</small>
      </li> : <li key={row.candidate_id} className={`queue-row ${row.state} ${row.candidate_id === me?.candidate_id ? "mine" : ""}`}>
        <span className="queue-rank">{row.position ?? "—"}</span>
        <div><strong className="queue-name">{row.full_name}</strong><small>{row.lab_title || `Работа ${row.lab_key}`} · <a href={`https://github.com/${encodeURIComponent(row.github)}`} target="_blank" rel="noreferrer">{row.github}</a></small></div>
        <small>{entryLabel(row)}</small>
      </li>)}
    </ol>
    {data && !data.entries?.length && !checking && <p className="queue-muted">Пока нет допущенных участников. После успешной проверки работа появится здесь.</p>}
    {data && !me && !checking && <p className="queue-muted">Для указанного GitHub допущенная работа пока не найдена. Успешно зарегистрируйте первую незащищённую лабораторную.</p>}
    {me && <div className="queue-notice">
      <strong>Придёте сдавать на это занятие?</strong>
      <p className="queue-attendance-hint" aria-live="polite">{!me.answered ? "По умолчанию вы не включены в состав приходящих." : me.will_attend ? "Приход подтверждён. Ответ можно изменить до начала занятия." : "Вы отметили, что не придёте. Ответ можно изменить до начала занятия."}</p>
      <div className="queue-actions">
        <button aria-pressed={me.will_attend} disabled={!data.attendance_open || data.stale || saving || checking || !canIdentify(identity)} onClick={() => choose(true)}>Да, я приду</button>
        <button aria-pressed={!me.will_attend} disabled={!data.attendance_open || data.stale || saving || checking || !canIdentify(identity)} onClick={() => choose(false)}>Нет, не приду</button>
      </div>
      {!data.attendance_open && <p>Изменение посещения недоступно для этого занятия.</p>}
      {!canIdentify(identity) && <p>Заполните ФИО и GitHub в форме выше.</p>}
    </div>}
    {saveError && <p role="alert" className="queue-notice queue-error">{saveError}</p>}
    <div className={`queue-feedback ${saving ? "is-saving" : ""}`} role="status" aria-live="polite"><span className="queue-spinner" aria-hidden="true" />{saving ? "Сохраняется ответ…" : ""}</div>
    <small>Ответ можно изменить до начала пары. Для возвращения к списку новая проверка не требуется.</small>
  </section>;
}
