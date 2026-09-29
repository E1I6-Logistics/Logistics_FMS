# Ollaya 기반 Laya 경로 후보 선택기

## 목적

Ollaya가 로컬에서 제공하는 Laya 의사결정 모델로 여러 경로 후보 중 하나를
선택한다. 경로 자체를 생성하거나 최단 거리를 계산하지 않는다. 최단 경로와
거리 계산은 기존 `route_service`가 담당하고, Laya는 이미 만들어진 후보를
선택하는 역할만 담당한다.

Ollaya와 Ollama는 서로 다른 프로그램이다. Ollama는 생성형 LLM 서버이고,
Ollaya는 Laya 같은 의사결정 모델을 제공하며 기본 포트는 `11435`이다.

## 코드 구성

- `simulation/route_selector/base.py`: 후보 선택기의 공통 인터페이스
- `simulation/route_selector/ollaya_laya_selector.py`: Ollaya `/api/decide` 호출
- `simulation/route_selector/registry.py`: `ROUTE_SELECTOR` 값으로 구현 선택
- `tests/test_ollaya_laya_selector.py`: 서버 없이 요청·응답 형식 검증

요청에는 상태와 두 개 이상의 후보를 전달한다. Ollaya 응답에서는 선택 ID,
신뢰도, 후보별 확률, 실제 checkpoint, 라우팅 정보와 실행 시간을 기록한다.
`laya` 모델명은 입력 언어에 따라 영어 또는 다국어 checkpoint를 자동 선택한다.

## 설치 및 서버 준비

원격 Linux 또는 WSL 터미널에서 Ollaya를 설치한다.

```bash
curl -fsSL https://ollaya.dev/install.sh | sh
ollaya --version
ollaya pull laya
ollaya list
```

설치 과정에서 서비스가 자동 시작되지 않았다면 별도 터미널에서 실행한다.

```bash
ollaya serve
```

서버 상태와 모델을 확인한다.

```bash
curl http://127.0.0.1:11435/api/tags
ollaya run laya --preset triage --verbose   "배송 로봇의 이동 경로를 선택해야 합니다."
```

## 프로젝트 설정

`simulation/.env`에 다음 값을 넣는다.

```dotenv
ROUTE_SELECTOR=ollaya_laya
OLLAYA_HOST=http://127.0.0.1:11435
OLLAYA_MODEL=laya
OLLAYA_TIMEOUT_SECONDS=10
# 서버에 OLLAYA_API_KEY를 설정한 경우에만 같은 값을 입력한다.
# OLLAYA_API_KEY=
```

Ollaya가 다른 컴퓨터에서 실행된다면 `OLLAYA_HOST`에 그 컴퓨터의 주소를
입력한다. 외부 접속 허용 범위와 방화벽 설정은 해당 장비에서 별도로 제한한다.

## 코드 구조 테스트

이 테스트는 Ollaya나 모델을 실행하지 않는다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest tests.test_ollaya_laya_selector -v
```

## Python에서 호출

```python
from simulation.route_selector import get_selector

selector = get_selector()
result = selector.select_route(
    {"start_node": 2, "target_node": 10},
    {
        "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
        "route_b": "path=[2,5,4,6,10], distance=1.592143",
    },
)
print(result)
```

반환값의 주요 필드는 다음과 같다.

- `choice`: 선택된 후보 ID
- `confidence`: 선택 신뢰도
- `probabilities`: 후보별 확률
- `model`: 실제 응답한 Laya checkpoint
- `total_duration_seconds`: 로딩을 포함한 전체 처리 시간
- `load_duration_seconds`: 모델 로딩 시간
- `eval_duration_seconds`: 추론 시간
- `raw`: Ollaya 원시 응답

후보 순서를 무작위로 바꾸어 정확도를 측정하는 3차 반복 테스트는 이 선택기를
사용해 별도 단계에서 구현한다.


## Choice 외 질문 타입 테스트

Ollaya의 `/api/decide`는 URL 하나에서 `choice`, `score`, `noul` 타입을 지원한다.
각 타입을 한국어와 영어로 분리하고 유형별 예열 1회, 본 시험 5회를 실행한다.
추가로 계획 경로 `[2, 5, 4, 6, 10]`에 차단 노드 `6`이 포함된 구조화된
상태를 전달해, 해당 경로를 사용할 수 없는지 `noul`로 판단하는 한국어·영어
케이스를 각각 실행한다.

| 타입 | 반환값 | 정답 판정 |
| --- | --- | --- |
| `choice` | 선택 label·확률·confidence | 정답 label과 일치 |
| `score` | 0부터 시작하는 연속 기대 점수 | 설정한 정답 범위에 포함 |
| `noul` | 진술이 참일 확률 | 0.5 임계값으로 참·거짓 판정 |

```bash
python -m simulation.evaluation.ollaya_question_types_benchmark \
  --model laya:multilingual \
  --warmups 1 \
  --repeats 5 \
  --output simulation/benchmark_results/laya-question-types-$(date +%Y%m%d-%H%M%S)
```

생성 파일은 `ollaya_question_type_trials.jsonl`,
`ollaya_question_type_summary.json`, `ollaya_question_type_samples.csv`다. 요약에는
한국어·영어와 질문 타입을 조합한 6개 그룹의 정확도와 지연시간이 저장된다.

구조만 검증하려면 다음을 실행한다.

```bash
python -m unittest tests.test_ollaya_question_types -v
```

## 언어·질문 복잡도·정답 위치별 테스트

각 질문은 선택지 5개를 사용한다. 같은 정답 내용을 유지하면서 정답을
`option_a`부터 `option_e`까지 한 번씩 옮겨 위치 편향을 확인한다. 한국어와
영어를 별도 케이스로 실행한다.

| 질문 유형 | 한국어 예시 | 영어 예시 |
| --- | --- | --- |
| 직관 | 명시된 라벨 색상 선택 | Select the stated label color |
| 사고 | 다섯 사람의 키 순서를 연결해 최댓값 선택 | Infer the tallest of five people |
| 최단거리 | 방향성 그래프에서 유효한 최단 후보 선택 | Select the valid shortest directed path |

총 케이스는 `3개 유형 × 2개 언어 × 정답 위치 5개 = 30개`다. 기본 반복 5회를
사용하면 본 시험은 150회이며, 한국어·영어 및 질문 유형별 예열 6회는 집계에서
제외한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.ollaya_latency_benchmark \
  --model laya:multilingual \
  --warmups 1 \
  --repeats 5 \
  --deadline 0.15 \
  --output simulation/benchmark_results/laya-v3-$(date +%Y%m%d-%H%M%S)
```

요약에는 한국어·영어와 질문 유형을 조합한 6개 그룹 통계, 정답 위치 5개별
통계, 전체 통계를 저장한다. 각 그룹에서 정확도, 평균, 중앙값, p95, 최솟값,
최댓값 및 0.15초 충족률을 비교할 수 있다.

### 실제 최단거리 검증 방식

이 지연시간 시험에서 경로 후보는
`routes/test_benchmark_v1.geojson`으로부터 만들어진다. 코드 기준 정답은
`simulation/services/route_service.py`의 `plan_route()`로 계산하고, 후보 경로의
방향성 간선과 거리는 `validate_and_calculate_path_distance()`로 다시 검증한다.
Laya에는 방향성 CompactRouteGraph와 경로 후보 5개를 전달한다.

이 시험은 **코드가 준비한 후보 중 Laya가 정답을 선택하는 시험**이다. LLM이
그래프 전체를 받아 경로를 직접 생성하고 코드 결과와 비교하는 방법은
`doc/llm-route-generation-benchmark.md`에 설명되어 있다. 실행 전 구조 검증은
다음 명령으로 수행한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --check
```

생성되는 분석 파일은 다음과 같다.

| 파일 | 내용 |
| --- | --- |
| `ollaya_laya_latency_trials.jsonl` | 언어·유형·정답 위치·반복별 원시 결과 |
| `ollaya_laya_latency_summary.json` | 전체·언어/유형·정답 위치별 통계 |
| `ollaya_laya_latency_samples.csv` | Excel과 그래프 작성용 개별 측정값 |

Mock 구조 검증 명령은 다음과 같다.

```bash
python -m unittest tests.test_ollaya_latency_benchmark -v
```
