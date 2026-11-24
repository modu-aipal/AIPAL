// Vercel 서버 함수: 브라우저 -> (이 파일이 키를 붙임) -> B 서버
// 키는 Vercel 환경변수 B_API_KEY 에만 있고, 브라우저로 내려가지 않는다.
export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ detail: 'Method Not Allowed' });
  const question = req.body && req.body.question;
  if (typeof question !== 'string' || !question.trim()) {
    return res.status(422).json({ detail: 'question이 필요합니다' });
  }
  // 이번 대화의 직전 질문(오래된 순). 배열이 아니면 무시, 최대 3개, 각 200자까지
  const raw = req.body && req.body.history;
  const history = Array.isArray(raw)
    ? raw.filter((h) => typeof h === 'string' && h.trim()).slice(-3).map((h) => h.slice(0, 200))
    : [];
  if (!process.env.B_API_URL || !process.env.B_API_KEY) {
    return res.status(500).json({ detail: '서버 설정(B_API_URL, B_API_KEY)이 없습니다' });
  }
  try {
    const r = await fetch(`${process.env.B_API_URL}/api/dashboard/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': process.env.B_API_KEY,
        'ngrok-skip-browser-warning': '1',
      },
      body: JSON.stringify({ question, history }),
    });
    res.status(r.status);
    for (const h of ['content-type', 'x-is-mock', 'x-data-source']) {
      const v = r.headers.get(h);
      if (v) res.setHeader(h, v);
    }
    res.send(await r.text());
  } catch (e) {
    res.status(502).json({ detail: 'AI 분석 서버에 연결할 수 없습니다' });
  }
}
