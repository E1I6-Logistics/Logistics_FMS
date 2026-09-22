# 기존 최단 경로와 Ollama LLM 경로 비교 실행 방법

`simulation/run_llm_comparison.py`는 동일한 경로 그래프를 대상으로 다음 결과를 비교한다.

1. `route_planner.py`가 계산한 기존 최단 경로
2. Ollama LLM이 계산한 경로

LLM이 응답한 거리값은 기록만 하고, 실제 비교 거리는 로컬 코드로 다시 계산한다. 이 명령은 프론트엔드, FastAPI, ROS 2, Zenoh, Docker, Mock Fleet 또는 실제 로봇을 실행하지 않아도 사용할 수 있다.

## 1. 프로젝트와 Python 가상환경 준비

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
```

Ollama Python SDK가 설치되어 있는지 확인한다.

```bash
python -c "import ollama; print('Ollama Python SDK OK')"
```

모듈을 찾을 수 없으면 프로젝트 의존성을 설치한다.

```bash
python -m pip install -r backend/requirements.txt
```

## 2. Ollama 서버와 모델 준비

Ollama 설치 및 서버 상태를 확인한다.

```bash
ollama --version
ollama list
curl http://localhost:11434/api/tags
```

서버가 실행되지 않았다면 별도 터미널에서 실행한다.

```bash
ollama serve
```

이미 포트를 사용 중이라는 메시지가 나오면 Ollama 서버가 실행 중인 것이므로 추가로 실행하지 않는다.

### 권장 모델

`gemma3:1b`는 테스트 그래프에서도 빈 경로를 반환하거나 긴 시간 생성한 사례가 있어 실제 비교에는 `qwen3:4b`부터 시험하는 것을 권장한다.

```bash
ollama pull qwen3:4b
```

다운로드를 확인한다.

```bash
ollama list
```

## 3. 환경설정

설정 파일을 연다.

```bash
nano simulation/.env
```

다음 값을 설정한다.

```dotenv
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:4b
OLLAMA_HOST=http://localhost:11434
LLM_ROUTE_GRAPH=test_compact_graph.geojson
LLM_TIMEOUT_SECONDS=60
PATH_DECISION_DEADLINE_SECONDS=0.15
LLM_MAX_ATTEMPTS=1
```

로컬 Ollama에는 API 키가 필요하지 않다. `simulation/.env`는 Git에 커밋하지 않는다.

이전에 터미널에서 다른 LLM 설정을 `export`했다면 해당 값이 `.env`보다 우선하므로 해제한다.

```bash
unset LLM_PROVIDER
unset OPENAI_MODEL
unset OPENAI_API_KEY
unset OLLAMA_MODEL
unset OLLAMA_HOST
unset LLM_ROUTE_GRAPH
unset LLM_TIMEOUT_SECONDS
unset PATH_DECISION_DEADLINE_SECONDS
unset LLM_MAX_ATTEMPTS
unset FMS_ROUTE_GRAPH
```

프로그램을 실행하면 `simulation/.env`를 다시 읽는다. `LLM_ROUTE_GRAPH`를 생략하면 원본 `routes/test.geojson`을 사용한다.

## 4. Compact Graph 생성과 선택

원본 GeoJSON에서 LLM 계산에 필요한 노드 ID, 방향성 엣지, 미리 계산한 엣지 거리만 추출한다.

```bash
python simulation/build_compact_graph.py
```

생성 파일은 다음과 같다.

```text
routes/test_compact_graph.geojson
```

실행할 때 파일을 직접 선택할 수 있다. 명령행의 `--llm-graph` 값이 `.env`의 `LLM_ROUTE_GRAPH`보다 우선한다.

```bash
# Compact Graph 선택
python simulation/run_llm_comparison.py \
  --start 2 \
  --goal 10 \
  --llm-graph test_compact_graph.geojson \
  --dry-run

# 원본 GeoJSON 선택
python simulation/run_llm_comparison.py \
  --start 2 \
  --goal 10 \
  --llm-graph test.geojson \
  --dry-run
```

코드 최단 경로는 계속 `FMS_ROUTE_GRAPH`의 원본 GeoJSON으로 계산한다. Compact Graph의 `source_graph`가 이 원본 파일과 다르면 비교를 중단한다.

## 5. 기존 최단 경로만 확인

LLM을 호출하지 않고 코드 경로만 계산한다.

```bash
python simulation/run_llm_comparison.py \
  --start 2 \
  --goal 10 \
  --dry-run
```

정상 출력 예시:

```text
경로 그래프와 코드 최단 경로를 계산합니다...
코드 경로: [2, 5, 4, 6, 10]
드라이런 완료: LLM은 호출하지 않았습니다.
```

## 6. Ollama 경로 비교 실행

무한 대기를 방지하기 위해 셸의 `timeout`을 적용해 실행한다.

```bash
timeout 120 python simulation/run_llm_comparison.py \
  --start 2 \
  --goal 10 \
  --llm-graph test_compact_graph.geojson \
  --max-attempts 1
```

주요 출력:

```text
코드 경로: [...]
ollama 모델 qwen3:4b에 요청 중...
LLM 경로: [...]
경로 일치: True 또는 False
거리 일치: True 또는 False
결과 파일: .../simulation/llm_route_comparisons.jsonl
```

종료 코드를 확인하려면 다음 명령을 실행한다.

```bash
echo $?
```

- `0`: 정상 완료
- `1`: 프로그램이 오류를 반환함
- `124`: `timeout 120`에 의해 종료됨

## 7. 결과 확인

비교 결과는 다음 파일에 JSONL 형식으로 누적된다.

```text
simulation/llm_route_comparisons.jsonl
```

마지막 결과를 보기 좋게 출력한다.

```bash
tail -n 1 simulation/llm_route_comparisons.jsonl | python -m json.tool
```

주요 필드:

```text
provider
model
input.start_node
input.target_node
baseline.path
baseline.recalculated_total_distance
llm.path
llm.reported_total_distance
llm.recalculated_total_distance
comparison.same_path
comparison.same_distance
comparison.distance_difference
metrics.json_response_success
metrics.valid_path
metrics.shortest_path_match
metrics.shortest_distance_match
metrics.absolute_distance_error
metrics.response_time_seconds
metrics.realtime_deadline_seconds
metrics.meets_realtime_deadline
metrics.timed_out
metrics.first_attempt_success
metrics.retry_success
metrics.input_character_count
metrics.estimated_input_tokens
```

성공과 실패 모두 JSONL에 기록된다. 각 실행 후 다음 누적 요약 파일도 자동으로 갱신된다.

```text
simulation/llm_route_summary.json
```

요약에는 provider·모델·프롬프트·그래프 파일별로 다음 값이 기록된다.

- JSON 응답 성공률
- 유효 경로 비율
- 최단 경로·최단 거리 일치율
- 평균 절대 거리 오차
- 평균 응답 시간
- 실시간 기준 시간과 충족률
- 타임아웃 비율
- 최초 성공률과 재시도 성공률
- 평균 입력 문자 수와 추정 토큰 수

기존 JSONL을 수동으로 다시 집계할 수도 있다.

```bash
python simulation/summarize_llm_comparisons.py
```

## 8. 다른 노드 조합 실행

```bash
timeout 120 python simulation/run_llm_comparison.py --start 0 --goal 10
timeout 120 python simulation/run_llm_comparison.py --start 1 --goal 12
timeout 120 python simulation/run_llm_comparison.py --start 2 --goal 13
```

존재하지 않는 노드이거나 방향성 경로가 연결되지 않은 경우 오류가 발생한다.

## 9. 실행이 오래 걸릴 때 확인

다른 터미널에서 Ollama 상태를 확인한다.

```bash
ollama ps
```

GPU 상태를 확인한다.

```bash
nvidia-smi
```

Ollama 서비스 로그를 확인한다.

```bash
journalctl -u ollama --since "10 minutes ago" --no-pager -n 100
```

실행 중인 비교를 직접 중단하려면 실행 터미널에서 `Ctrl+C`를 누른다.

### 빈 경로가 반환되는 경우

작은 모델이 그래프를 제대로 해석하지 못하면 다음과 같은 결과가 나올 수 있다.

```json
{
  "path": [],
  "reported_total_distance": 0.0
}
```

이 경우 더 큰 모델로 변경하고 다시 실행한다.

```bash
ollama pull qwen3:4b
```

```dotenv
OLLAMA_MODEL=qwen3:4b
```

### HTTP 500이 발생하는 경우

Ollama 로그와 실행 상태를 확인한 후 모델을 다시 로드한다.

```bash
ollama stop qwen3:4b
ollama run qwen3:4b
```

간단한 응답이 확인되면 `/bye`로 종료하고 비교 명령을 다시 실행한다.
