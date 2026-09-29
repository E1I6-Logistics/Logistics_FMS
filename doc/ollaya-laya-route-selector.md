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

## 질문 복잡도별 지연시간 테스트

동일한 Laya choice API에 다음 세 가지 질문을 전달해 복잡도에 따른 시간을
비교한다.

| 유형 | 입력 | 정답 |
| --- | --- | --- |
| 직관 질문 | 라벨 색상이 파란색이라고 직접 명시 | `blue` |
| 사고 질문 | 민수 > 영희 > 철수 조건에서 가장 큰 사람 선택 | `minsu` |
| 최단거리 질문 | 두 경로의 유효성과 거리 비교 | `route_b` |

Laya는 생성형 LLM처럼 숨은 사고 과정이나 사고 토큰을 제공하지 않는다. 따라서
여기서 사고 질문은 여러 조건을 연결해야 정답을 고를 수 있는 문제를 뜻한다.
측정값은 실제 API 호출 전후의 시간과 Ollaya가 반환한 내부 처리시간이다.

예열은 질문 유형별 1회이며 통계에서 제외한다. `--repeats 30`은 유형마다
30회 실행한다는 뜻이므로 본 시험은 총 `3 × 30 = 90회`다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.ollaya_latency_benchmark \
  --model laya:multilingual \
  --warmups 1 \
  --repeats 30 \
  --deadline 0.15 \
  --output simulation/benchmark_results/laya-complexity-$(date +%Y%m%d-%H%M%S)
```

`wall_seconds`는 통신과 직렬화를 포함한 체감시간이고, `ollaya_total_seconds`는
Ollaya 서버 내부 전체 시간이며, `eval_seconds`는 모델 추론시간이다. 실시간
기준은 `wall_seconds <= 0.15`로 판정한다. 요약 파일에는 전체 통계와 세 유형별
정확도, 평균, 중앙값, p95, 최솟값, 최댓값, 실시간 기준 충족률이 각각 저장된다.

| 파일 | 내용 |
| --- | --- |
| `ollaya_laya_latency_trials.jsonl` | 유형·반복별 선택 결과, 신뢰도와 모든 시간 |
| `ollaya_laya_latency_summary.json` | 전체 및 유형별 정확도·지연시간 통계 |
| `ollaya_laya_latency_samples.csv` | Excel과 그래프 작성용 개별 측정값 |

Ollaya를 호출하지 않고 구조만 확인하려면 다음을 실행한다.

```bash
python -m unittest tests.test_ollaya_latency_benchmark -v
```
