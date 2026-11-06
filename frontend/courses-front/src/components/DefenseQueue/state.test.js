import test from "node:test";
import assert from "node:assert/strict";
import { cleanIdentity, ownEntry, canIdentify, entryLabel, identityKey } from "./state.js";

test("identity keeps only known string fields", () => {
  assert.deepEqual(cleanIdentity({ name: "Имя", github: 42, admin: true }), { surname: "", name: "Имя", patronymic: "", github: "" });
  assert.equal(canIdentify({ surname: "Ф", name: "И", github: "login" }), true);
  assert.equal(canIdentify({ surname: "Ф", name: "И", github: "  " }), false);
});
test("student matching is case insensitive", () => {
  const row = { github: "Login", candidate_id: 3 };
  assert.equal(ownEntry([row], " LOGIN "), row);
  assert.equal(ownEntry([row], "other"), undefined);
});
test("current, next and repeat states are distinct", () => {
  const row = { attempt: { entry_id: 2, status: "waiting", is_repeat: 1 } };
  assert.equal(entryLabel(row, { current: 2 }), "Сдаёт сейчас");
  assert.equal(entryLabel(row, { next: 2 }), "Следующий · повторно");
  assert.equal(entryLabel({ state: "unconfirmed" }), "Не подтверждено");
  assert.equal(entryLabel({ state: "declined" }), "Не придёт");
});
test("storage keys cannot collide through separators", () => {
  assert.notEqual(identityKey("a.b", "c"), identityKey("a", "b.c"));
});
