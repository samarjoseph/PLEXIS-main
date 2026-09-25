export function extractResponseText(response) {
  if (!response) {
    return 'Analysis successfully derived with zero structural observations.';
  }

  if (typeof response === 'string') return response;

  if (typeof response === 'object') {
    if (response.reply && typeof response.reply === 'object') {
      if (typeof response.reply.answer === 'string') return response.reply.answer;
      if (typeof response.reply.text === 'string') return response.reply.text;
    }

    if (response.explanation && typeof response.explanation === 'object') {
      if (typeof response.explanation.answer === 'string') return response.explanation.answer;
      if (typeof response.explanation.text === 'string') return response.explanation.text;
    }

    if (typeof response.answer === 'string') return response.answer;
    if (typeof response.explanation === 'string') return response.explanation;
    if (typeof response.text === 'string') return response.text;

    try {
      return JSON.stringify(response);
    } catch {
      return 'Unparsable analytical response payload format.';
    }
  }

  return String(response);
}

export function extractMetadata(response) {
  const defaultMeta = {
    source: null,
    provider: null,
    webSuccess: false,
    sources: [],
    citations: [],
  };

  if (!response || typeof response !== 'object') return defaultMeta;

  const target = response.reply || response.explanation || response;

  return {
    source: target.source || response.source || null,
    provider: target.provider || response.provider || null,
    webSuccess:
      target.web_success !== undefined
        ? target.web_success
        : response.web_success !== undefined
          ? response.web_success
          : false,
    sources: target.sources || response.sources || [],
    citations: target.citations || response.citations || [],
  };
}
