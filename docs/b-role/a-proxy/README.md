# A에게: 이 폴더의 `api/` 를 대시보드 프로젝트에 복사하세요

1. 이 폴더의 `api/` 폴더를 **대시보드 프로젝트의 루트**에 그대로 복사한다 (`api/dashboard/analyze.js`, `api/health.js`).
2. Vercel → Project Settings → Environment Variables 에 2개 등록 (Production·Preview 모두)
   - `B_API_URL` = B가 전달한 ngrok 주소 (끝에 `/` 없이)
   - `B_API_KEY` = B가 전달한 키  (`NEXT_PUBLIC_` 접두사 금지)
3. `index.html` 의 API 주소를 **대시보드 자신의 주소**로 바꾼다.
   `<meta name="aipal-api" content="https://<vercel 주소>">`
4. 재배포.
5. 확인: 대시보드에서 "추정매출이 뭐야?" 입력 → 답이 나오면 성공.
   브라우저 개발자도구 Network 요청 헤더에 `X-API-Key` 가 **없어야** 정상.

키는 `index.html` 등 화면 코드에 절대 넣지 마세요.
