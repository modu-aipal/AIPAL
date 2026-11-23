"""C 계산 엔진 서버. B의 HttpCalculator가 POST {CALC_ENGINE_URL}/calculate 로 호출한다.

실행 (저장소 최상단에서): python -m uvicorn calc_engine.main:app --port 8100
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from calc_engine.data import DATA_SOURCE, DATA_VERSION, DATASET_ID, DEFAULT_DATA, load_sales_csv, load_store_csv
from calc_engine.engine import calculate

DF = load_sales_csv(DEFAULT_DATA)
STORES = load_store_csv()

app = FastAPI(title="AIPAL C 계산 엔진", version="1.1")


@app.get("/health")
def health():
    quarters = sorted(DF["기준_년분기_코드"].unique())
    return {"status": "ok", "dataset_id": DATASET_ID, "data_version": DATA_VERSION, "data_source": DATA_SOURCE,
            "rows": len(DF), "store_rows": len(STORES), "quarters": [quarters[0], quarters[-1]]}


@app.post("/calculate")
async def calculate_route(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    status, payload = calculate(DF, body if isinstance(body, dict) else {}, STORES)
    return JSONResponse(payload, status_code=status)
