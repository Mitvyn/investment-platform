import assert from "node:assert/strict";
import test from "node:test";

import {
  addMoomooClientId,
  parseMoomooAutoResumeClientId,
  parseMoomooClientIds,
  serializeMoomooClientIds,
} from "./moomoo-client-preferences.ts";

test("auto resume requires one explicit valid client preference", () => {
  const clientId = "85b4a889-740d-4f3a-b49e-9ca9903e1e59";

  assert.equal(parseMoomooAutoResumeClientId(undefined), null);
  assert.equal(parseMoomooAutoResumeClientId("disabled"), null);
  assert.equal(parseMoomooAutoResumeClientId("invalid"), null);
  assert.equal(parseMoomooAutoResumeClientId(clientId), clientId);
});

test("saved Moomoo client IDs are validated, deduplicated, and newest first", () => {
  const first = "85b4a889-740d-4f3a-b49e-9ca9903e1e59";
  const second = "4a8bcd69-e915-4778-9583-17ad0e9e6a80";

  const saved = addMoomooClientId([first, "invalid", second], first);

  assert.deepEqual(saved, [first, second]);
  assert.deepEqual(parseMoomooClientIds(serializeMoomooClientIds(saved)), saved);
});

test("saved Moomoo client ID cookie stays bounded", () => {
  const values = Array.from(
    { length: 7 },
    (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
  );

  assert.deepEqual(addMoomooClientId(values, values[6]), [
    values[6],
    values[0],
    values[1],
    values[2],
    values[3],
  ]);
});
