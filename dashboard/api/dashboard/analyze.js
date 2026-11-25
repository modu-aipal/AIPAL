// Vercel 서버 함수: 브라우저 -> (이 파일이 키를 붙임) -> B 서버
// 키는 Vercel 환경변수 B_API_KEY 에만 있고, 브라우저로 내려가지 않는다.

// 요청 횟수 제한: 한 IP 가 1분에 LIMIT 번까지. B 서버는 PC 한 대가 답을 만들기 때문에 계속 두드리면 모두가 느려진다.
// 기록은 이 함수 인스턴스의 메모리에만 있다. Vercel 이 인스턴스를 여러 개 띄우면 각각 따로 세므로 완벽한 제한은 아니다
// (한 사람이 계속 보내는 경우는 대부분 막는다). 더 단단한 제한은 Vercel Firewall 규칙이나 B 서버에서 한다.
const LIMIT = 10;
const WINDOW_MS = 60 * 1000;
const MAX_QUESTION = 1000; // B 서버(DashboardRequest)와 같은 길이 제한
const hits = new Map(); // ip -> 최근 요청 시각들

function clientIp(req) {
  const xff = req.headers['x-forwarded-for'];
  const first = typeof xff === 'string' ? xff.split(',')[0].trim() : '';
  return first || req.headers['x-real-ip'] || (req.socket && req.socket.remoteAddress) || 'unknown';
}

// 남은 대기 시간(초). 0 이면 통과
function rateLimited(ip, now) {
  const recent = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  if (recent.length >= LIMIT) {
    hits.set(ip, recent);
    return Math.max(1, Math.ceil((WINDOW_MS - (now - recent[0])) / 1000));
  }
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 5000) {
    for (const [k, v] of hits) if (!v.length || now - v[v.length - 1] >= WINDOW_MS) hits.delete(k);
  }
  return 0;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ detail: 'Method Not Allowed' });
  const question = req.body && req.body.question;
  if (typeof question !== 'string' || !question.trim()) {
    return res.status(422).json({ detail: 'question이 필요합니다' });
  }
  if (question.length > MAX_QUESTION) {
    return res.status(422).json({ detail: `질문은 ${MAX_QUESTION}자까지 보낼 수 있어요` });
  }
  const wait = rateLimited(clientIp(req), Date.now());
  if (wait) {
    res.setHeader('Retry-After', String(wait));
    return res.status(429).json({ detail: `질문이 너무 잦아요. ${wait}초 뒤에 다시 물어봐 주세요`, retry_after: wait });
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
