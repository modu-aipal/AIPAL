// Vercel 서버 함수: B 서버 연결 상태 확인 (키 불필요, 주소만 숨겨 같은 오리진으로 제공)
export default async function handler(req, res) {
  if (!process.env.B_API_URL) return res.status(500).json({ detail: '서버 설정(B_API_URL)이 없습니다' });
  try {
    const r = await fetch(`${process.env.B_API_URL}/health`, {
      headers: { 'ngrok-skip-browser-warning': '1' },
    });
    res.status(r.status).setHeader('content-type', 'application/json').send(await r.text());
  } catch (e) {
    res.status(502).json({ detail: 'AI 분석 서버에 연결할 수 없습니다' });
  }
}
