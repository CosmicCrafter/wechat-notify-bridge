export const errors = {
  client_receive_unavailable:
    "所属应用暂无有效接收凭据，请联系管理员恢复授权。",
  image_too_large: "图片过大，请选择较小的图片。",
  invalid_image: "无法读取图片，请选择 JPG、PNG 或 WebP。",
  image_storage_full: "图片空间已满，请清理不需要的对话。",
  too_many_pending_images: "待发送图片较多，请稍后再试。",
  image_not_found: "图片不存在或已清理。",
  image_already_sent: "图片已经发送，请重新选择。",
  image_dimensions_unsupported: "图片尺寸或格式不支持，请尝试截图后发送。",
  conversation_name_conflict:
    "已有同名有效对话。请先归档同名对话，再恢复这一条。",
  login_required: "请重新登录。",
  invalid_login_code: "登录码不正确，请检查管理员或微信提供的 8 位数字。",
  login_code_expired:
    "登录码已过期或尝试次数过多，请管理员生成新码，或在微信重新发送 /web。",
  conversation_closed: "这个对话已结束或客户端已停用，暂时无法回复。",
  conversation_not_found: "对话不存在，请从列表重新选择。",
  message_not_found: "未找到链接指向的消息，请从对话列表进入。",
  request_id_content_conflict: "本次重试内容不一致，请保留原内容重试。",
};

Object.assign(errors, {
  task_not_found: "这张任务卡片不存在或已清理。",
  invalid_task_choice: "选项已失效，请重新打开卡片。",
  task_answer_required: "请选择一个方案，或写下你的安排。",
  task_already_answered: "这张卡片已经答复，不能重复更改决定。",
  task_not_pending: "这张卡片已经取消或结束。",
  task_expired: "这张卡片已过期，请在对话中请 AI 重新发起。",
  task_state_conflict: "任务状态已变化，请刷新查看。",
});
errors.task_choice_limit = "选择数量不符合这张卡片的要求，请调整后提交。";
Object.assign(errors, {
  invalid_conversation_name:
    "名称格式不正确，请使用 1–20 位中英文、数字、下划线或短横线。",
  conversation_name_conflict: "已有同名有效对话，请使用另一个名称。",
  invalid_task_fields: "表单内容格式不正确，请检查选项、数字或日期。",
  task_field_required: "请填写所有必填项。",
});
