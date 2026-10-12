export function taskCanSubmit(task, draft) {
  const mode = task.mode || "single";
  if (mode === "form")
    return task.fields.every(
      (f) => !f.required || !!(draft.field_values[f.id] || "").trim(),
    );
  if (mode === "input") return !!draft.text.trim();
  if (mode === "multiple") {
    const n = draft.choice_ids.length;
    return n
      ? n >= task.min_choices && n <= task.max_choices
      : task.allow_custom && !!draft.text.trim();
  }
  return (
    draft.choice_id !== undefined &&
    (draft.choice_id !== null || (task.allow_custom && !!draft.text.trim()))
  );
}
export function taskAnswerPayload(task, draft) {
  if (task.mode === "form") return { field_values: { ...draft.field_values } };
  if (task.mode === "multiple")
    return {
      choice_ids: [...draft.choice_ids],
      text: task.allow_custom ? draft.text : "",
    };
  if (task.mode === "input") return { choice_id: null, text: draft.text };
  return {
    choice_id: draft.choice_id,
    text: draft.choice_id === null ? draft.text : "",
  };
}
