const originalFetch = globalThis.fetch;

function safeText(value) {
  return String(value ?? '')
    .replace(/data:[^\s"']+/g, '[REDACTED_DATA]')
    .replace(/Bearer\s+[^\s"']+/gi, 'Bearer [REDACTED]')
    .replace(/eyJ[A-Za-z0-9_.-]+/g, '[REDACTED_TOKEN]')
    .replace(/\b(?:sk-|rt_)[A-Za-z0-9_-]+/g, '[REDACTED_SECRET]')
    .replace(/https?:\/\/[^\s"']+/g, '[REDACTED_URL]')
    .slice(0, 500);
}

globalThis.fetch = async (...argumentsList) => {
  const response = await originalFetch(...argumentsList);
  if (!response.ok) {
    let payload;
    try {
      payload = await response.clone().json();
    } catch {
      payload = {};
    }
    const detail = payload?.error ?? payload?.detail ?? payload;
    console.error('IMAGE_BACKEND_DIAGNOSTIC=' + JSON.stringify({
      status: response.status,
      type: safeText(detail?.type),
      code: safeText(detail?.code),
      param: safeText(detail?.param),
      message: safeText(typeof detail === 'string' ? detail : detail?.message),
    }));
  }
  return response;
};
