# 로컬 모델 경로 생성·선택 반복 테스트

이 문서는 코드로 계산한 최단 경로와 Ollama 로컬 모델이 생성한 경로를
반복 비교하고, Hugging Face Laya가 경로 후보를 선택하는 성능을 측정하는
방법을 설명한다. 이 실행기는 로봇 이동 명령을
보내지 않으며 FastAPI, ROS 2, Zenoh, 데이터베이스를 사용하지 않는다.

## 1. 재현 기준

설정 파일은 `simulation/evaluation/route_generation_benchmark.json`이다. 2026-09-28에
진행한 2차 테스트 조건을 다음과 같이 고정한다.

| 항목 | 값 |
| --- | --- |
| 기준 커밋 | `1e7535c9e276a1a5e0ab3ba9770c56e4bb0f68fc` |
| 그래프 | `routes/test_benchmark_v1.geojson` |
| 그래프 SHA-256 | `00e1f02cce0f5007342dfef4c7c1a0d95f36eb639c530dcf0c8e7c7ce0f304c3` |
| 프롬프트 SHA-256 | `53276490f7224be85126a1576d519d132566193b9bd7fec7d32b4e38f4cbfe44` |
| 그래프 크기 | 노드 14개, 유향 간선 28개 |
| 모델 | `qwen3:0.6b`, `qwen3:1.7b`, `gemma3:1b`, `qwen3:4b`, `deepseek-r1:14b` |
| 경로 | `0→6`, `1→12`, `2→10` |
| 반복 | 모델·경로 조합별 3회 |
| 예열 | 모델별 1회, 본 시험 집계에서 제외 |
| 생성 설정 | `temperature=0`, `seed=20260928`, `num_ctx=4096`, `num_predict=512` |
| 추론 모드 | qwen3 모델은 `think=false`, gemma3에는 `think`를 전달하지 않음 |
| 제한 시간 | 요청당 120초 |
| 최대 시도 | 1회 |
| 모델 유지 | `keep_alive=5m` |
| 실시간 판단 기준 | 0.15초 |

0.15초는 요청 제한 시간이 아니다. `timeout_seconds=120`은 응답을 기다리는
최대 시간이고, `realtime_deadline_seconds=0.15`는 응답 완료 후 실시간 기준을
충족했는지 분류하는 값이다.

설정 파일에는 기준 경로와 거리도 함께 저장한다. 실행 전 코드가 다시 계산한
경로·거리, 그래프 개수, 그래프 SHA-256 중 하나라도 기준과 다르면 테스트를
중단한다. 따라서 그래프나 최단 경로 코드가 달라진 상태에서 이전 실험과 같은
이름으로 결과를 만드는 것을 방지한다.

## 2. LLM 프롬프트

실제로 사용하는 영문 프롬프트 전문은
`simulation/evaluation/route_generation_benchmark.json`의 `prompt`에 저장한다. 핵심 규칙은
다음과 같다.

- 입력은 시작 노드, 도착 노드, CompactRouteGraph이다.
- 간선은 `from`에서 `to` 방향으로만 이동한다.
- 간선의 `weight`를 그대로 사용한다.
- Dijkstra 알고리즘으로 총가중치가 가장 작은 경로를 찾는다.
- 시작·도착 노드와 모든 연속 간선의 유효성을 확인한다.
- JSON Schema에 맞는 객체만 반환한다.

실행 결과의 `manifest.json`에는 프롬프트 SHA-256을 기록한다. 프롬프트를
변경하여 실험할 경우 기존 결과 폴더를 재사용하지 말고 설정 파일과
`benchmark_id`를 새 버전으로 만든다.

## 3. 실행 전 구조 검증

원격 컴퓨터의 WSL 터미널에서 실행한다.

```bash
cd ~/Logistics_FMS
git branch --show-current
source ~/venv/robot/bin/activate
python -m pip install -r simulation/requirements.txt
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --check
```

`--check`는 Ollama에 요청하지 않는다. 그래프 해시, 노드·간선 개수,
코드 최단 경로와 기준값만 확인한다.

Ollama 없이 전체 반복·저장·집계·재개 구조를 확인하려면 Mock 테스트를 실행한다.

```bash
python -m unittest tests.test_route_generation_benchmark -v
python -m unittest tests.test_ollama_provider -v
```

Mock 테스트는 모델 성능을 평가하지 않는다. 5개 모델 × 3개 경로 × 3회인
45개 본 시험과 모델별 예열 5개가 분리되는지, CSV가 생성되는지, 완료된
결과를 재실행하지 않는지만 빠르게 확인한다.

## 4. Ollama 및 모델 준비

Ollama 서버와 설치된 모델을 확인한다.

```bash
ollama --version
ollama list
curl http://127.0.0.1:11434/api/tags
```

서버가 동작하지 않으면 별도 터미널에서 실행한다.

```bash
ollama serve
```

v3 시험에 사용할 모델 10종 중 누락된 모델만 내려받는다. 기본 모델
파일의 합은 약 48GB이므로 먼저 `df -h`로 저장 공간을 확인한다.

```bash
ollama pull qwen3:0.6b
ollama pull deepseek-r1:1.5b
ollama pull llama3.2:3b
ollama pull qwen3:4b
ollama pull gemma3:4b
ollama pull llama3.1:8b
ollama pull mistral-nemo:12b
ollama pull gemma3:12b
ollama pull deepseek-r1:14b
ollama pull phi4:14b
```

다른 컴퓨터의 Ollama 서버를 사용하면 실행 전에 주소를 지정한다.

```bash
export OLLAMA_HOST=http://서버주소:11434
```

## 5. Jetson 또는 원격 컴퓨터에서 본 시험 실행

결과 폴더 이름에는 장비와 실행 시각을 넣는 것을 권장한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --output simulation/benchmark_results/jetson-v3-$(date +%Y%m%d-%H%M%S)
```

실행기는 모델별 예열을 먼저 수행하고 다음으로 각 경로를 3회 실행한다.
터미널에는 모델, 경로, 반복 번호, 유효 경로 여부, 최단 거리 일치 여부,
응답 시간이 한 줄씩 출력된다.

실행이 중단되면 같은 폴더를 `--resume`에 전달한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --resume simulation/benchmark_results/jetson-v3-실행시각
```

이미 기록된 예열과 `모델·시작·도착·반복 번호` 조합은 다시 요청하지 않는다.
설정 파일 또는 그래프 해시가 원래 실행과 다르면 재개를 거부한다.

## 6. 생성되는 파일

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태, 장비, Ollama 버전, 모델 정보, 그래프·프롬프트·설정 해시 |
| `warmups.jsonl` | 모델별 예열 응답과 시간. 정확도·지연시간 집계에서는 제외 |
| `trials.jsonl` | 본 시험의 입력, 원시 추론 정보, 응답, 재계산 결과, 모든 지표 |
| `summary.json` | 모델별·경로별 집계 결과 |
| `model_summary.csv` | 모델 간 정확도와 지연시간 그래프 작성용 |
| `route_summary.csv` | 모델·경로별 난이도 비교 그래프 작성용 |
| `latency_samples.csv` | 모든 개별 실행의 지연시간 분포 그래프 작성용 |
| `trial_samples.csv` | 개별 실행의 경로·거리·정확도·시간을 한 행으로 펼친 분석용 |



Ollama를 다시 실행하지 않고 저장된 `trials.jsonl`에서 요약과 CSV를 다시
만들려면 다음 명령을 사용한다.

```bash
python -m simulation.evaluation.benchmark \
  --export-results simulation/benchmark_results/jetson-v3-실행시각
```

이 명령은 모델에 요청하지 않고 `summary.json`, `model_summary.csv`,
`route_summary.csv`, `latency_samples.csv`, `trial_samples.csv`를 재생성한다.

CSV는 Excel에서 한글이 깨지지 않도록 UTF-8 BOM 형식으로 저장한다.
실행 결과 폴더는 `.gitignore`에 포함되므로 결과를 공유할 때는 별도 보관한다.

## 7. 기록 지표

각 본 시험에서 다음 값을 기록한다.

- JSON 객체 파싱 성공 여부
- 방향성 간선으로 연결된 유효 경로 여부
- 기준 최단 경로와 노드 배열이 같은지
- 코드가 재계산한 최단 거리와 같은지
- 절대 거리 오차
- 모델 보고 거리와 코드 재계산 거리의 오차
- 전체 응답 시간
- 0.15초 실시간 기준 충족 여부
- 제한 시간 초과 여부
- 최초 시도 성공 및 재시도 성공 여부
- 입력 문자 수와 추정 토큰 수
- Ollama 원시 요청·응답, 종료 이유 및 제공되는 토큰 수

정답 판정에는 모델이 보고한 거리를 사용하지 않는다. 모델이 반환한 경로를
공통 `route_service`로 다시 검증하고 계산한 거리만 사용한다.

과거 5종 v2 시험을 그대로 재현해야 할 때만 다음 설정을 지정한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark.json \
  --check
```

## 8. 재현성의 범위

고정된 그래프·프롬프트·모델 digest·파라미터·seed를 사용하면 논리적인 시험
조건을 재현할 수 있다. 응답 시간은 장비, Ollama 버전, 드라이버, 발열 및
다른 프로세스의 부하에 따라 달라지므로 이전 컴퓨터와 동일한 숫자가 나오는
것을 보장하지 않는다. 이 차이를 비교할 수 있도록 장비와 런타임 정보가
`manifest.json`에 저장된다.

## 9. 대표 로컬 모델 10종 확장 평가

`route-generation-v2`는 과거 2차 시험의 소형 모델 조건을 재현하기 위해
보존한다. 실제 후보 선정을 위한 확장 설정은
`simulation/evaluation/route_generation_benchmark_v3.json`을 사용한다.

1차 단일 실행에서는 `deepseek-r1:14b`가 약 33초, `qwen3:0.6b`가
약 39초로 성공했고 `deepseek-r1:1.5b`는 실패했다. 작은 모델이 항상
빠르거나 정확하지는 않았으므로 성공·실패 기준 모델을 모두 포함한다.
0.6B부터 14B까지 크기와 모델 계열을 분산하여 정확도, 응답 시간, 메모리
사용량의 변화를 비교한다.

| 모델 | 파라미터 | Ollama 기본 파일 크기 | 비교 역할 |
| --- | ---: | ---: | --- |
| `qwen3:0.6b` | 0.6B | 523MB | 1차 성공 초경량 기준 |
| `deepseek-r1:1.5b` | 1.5B | 1.1GB | 1차 실패 초경량 기준 |
| `llama3.2:3b` | 3B | 2.0GB | Meta 경량 비교군 |
| `qwen3:4b` | 4B | 2.5GB | 기존 반복 시험의 최고 정확도 모델 |
| `gemma3:4b` | 4B | 3.3GB | Google 경량 비교군 |
| `llama3.1:8b` | 8B | 4.9GB | Meta 중형 비교군 |
| `mistral-nemo:12b` | 12B | 7.1GB | Mistral·NVIDIA 중대형 비교군 |
| `gemma3:12b` | 12B | 8.1GB | Gemma 계열 크기 증가 비교군 |
| `deepseek-r1:14b` | 14B | 9.0GB | 1차 시험 최단 시간 성공 기준 |
| `phi4:14b` | 14B | 9.1GB | Microsoft 일반·논리 비교군 |

Qwen은 0.6B와 4B, Gemma는 4B와 12B를 함께 포함하여 동일 계열에서
크기 증가가 정확도와 지연시간에 미치는 영향을 확인한다. DeepSeek는 1차
실패 모델인 1.5B와 성공 모델인 14B를 함께 포함한다.

모델 정보 출처는 Ollama 공식 모델 페이지다:
[`qwen3`](https://ollama.com/library/qwen3/tags),
[`deepseek-r1`](https://ollama.com/library/deepseek-r1),
[`llama3.2`](https://ollama.com/library/llama3.2),
[`gemma3`](https://ollama.com/library/gemma3),
[`llama3.1`](https://ollama.com/library/llama3.1),
[`mistral-nemo`](https://ollama.com/library/mistral-nemo),
[`phi4`](https://ollama.com/library/phi4).

기본 모델 파일의 합은 약 48GB다. Jetson에서 전부 다운로드하기 전에
`df -h`로 저장 공간을 확인하고, 모델별 로딩 가능 여부와 메모리 사용량을
순서대로 점검한다.

시험 경로는 노드 수가 3, 4, 5, 5, 8개인 다섯 경로로 구성한다.

| 출발→도착 | 기준 최단 경로 | 거리 |
| --- | --- | ---: |
| 0→4 | 0 → 3 → 4 | 0.840354 |
| 0→6 | 0 → 3 → 4 → 6 | 1.234618 |
| 2→10 | 2 → 5 → 4 → 6 → 10 | 1.592143 |
| 1→12 | 1 → 4 → 6 → 13 → 12 | 1.899060 |
| 7→2 | 7 → 8 → 9 → 10 → 6 → 4 → 5 → 2 | 2.672242 |

각 모델은 예열 1회를 제외하고 경로별 5회씩 실행한다. 총 본 시험 수는
`10개 모델 × 5개 경로 × 5회 = 250회`이며 예열은 10회다. 생성 설정과 프롬프트는 v2와
동일하다. `deepseek-r1`과 `qwen3`은 직접 JSON 응답의 조건을 맞추기 위해
`think=false`를 요청한다. 장비에서 지원하는 thinking 값은 실행 전에
`/api/show`로 확인한다.



Jetson 접속이 가능해진 뒤 다음 명령으로 설정만 먼저 검증한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --check
```

실제 실행 명령은 다음과 같다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --output simulation/benchmark_results/jetson-v3-$(date +%Y%m%d-%H%M%S)
```

Jetson의 메모리 용량과 모델 로딩 가능 여부가 확인되지 않았으므로 최종 모델
확정은 보류한다. 모델을 불러올 수 없으면 실패 기록을 보존하고, 같은 용량대의
대체 모델 선정 여부를 별도로 결정한다.


## 10. Hugging Face Laya 경로 선택 시험

앞의 Ollama 시험은 모델이 최단 경로를 직접 생성하는 능력을 평가한다.
Laya 시험은 코드가 계산한 여러 경로 후보 중 하나를 선택하는 능력을 평가한다.
Laya가 최단 경로 알고리즘을 대신하지 않으며, 두 시험 결과를 같은 지표로
해석하지 않는다.

### 10.1 대상 장비와 실행 정책

- 장비: Jetson Orin Nano Developer Kit, RAM 8GB
- 프로젝트에서 사용할 수 있는 RAM: 약 4.5GB
- 사용할 수 있는 저장공간: 약 15GB
- 모델: `convaiinnovations/laya-multilingual` checkpoint 하나
- 기본 입력 한도: 1,024 tokens
- 동시 추론: 한 번에 한 요청
- CUDA를 사용할 수 없거나 CPU fallback이 발생하면 실패 처리

Laya Router의 `preload=True`는 여러 checkpoint를 함께 메모리에 올리므로
사용하지 않는다. TileLang fast extra도 기본 CUDA 경로를 검증하기 전에는
설치하지 않는다. 모델 파일은 Git에 저장하지 않으며 첫 실행 때 Hugging Face
cache로 내려받는다.
Laya Multilingual checkpoint는 약 647MB이며 Python 환경과 JetPack용 PyTorch 용량은 별도다.

관련 코드는 다음과 같다.

- `simulation/route_selector/laya_selector.py`: 모델 로드와 typed decision 처리
- `simulation/route_selector/registry.py`: `ROUTE_SELECTOR=laya` 선택
- `simulation/requirements-laya-jetson.txt`: Jetson용 Laya 의존성
- `tests/test_laya_selector.py`: 모델 다운로드가 없는 Mock 구조 테스트
- `simulation/evaluation/selector_latency_benchmark.py`: 언어·난이도·정답 위치별 경로 선택 시험
- `simulation/evaluation/selector_question_types_benchmark.py`: choice·score·noul 시험

### 10.2 Jetson CUDA PyTorch 확인

JetPack 버전에 맞는 NVIDIA 제공 PyTorch를 먼저 설치해야 한다. 일반 PyPI의
CPU용 PyTorch로 교체하지 않는다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -c "import torch; print('torch=', torch.__version__); print('cuda=', torch.cuda.is_available()); print('device=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
```

다음 조건을 만족해야 한다.

```text
cuda= True
device= Orin
```

`cuda=False`이면 Laya 설치보다 먼저 현재 JetPack과 호환되는 CUDA PyTorch를
설치한다.

### 10.3 저장공간과 Hugging Face cache 설정

```bash
df -h ~
free -h
mkdir -p ~/.cache/huggingface
export HF_HOME="$HOME/.cache/huggingface"
```

15GB 저장공간 안에서 중복 다운로드를 막으려면 모든 실행 터미널에서 같은
`HF_HOME`을 사용한다.

### 10.4 Laya 런타임 설치

CUDA가 동작하는 기존 Python 환경에서 설치한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m pip install -r simulation/requirements-laya-jetson.txt
python -m pip check
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

설치 후에도 `torch.cuda.is_available()`이 `True`인지 확인한다.

### 10.5 환경변수 설정

`simulation/.env`에 다음 값을 설정한다.

```dotenv
ROUTE_SELECTOR=laya
LAYA_HF_MODEL=convaiinnovations/laya-multilingual
LAYA_DEVICE=cuda:0
LAYA_REQUIRE_CUDA=true
LAYA_MAX_LENGTH=1024
HF_HOME=/home/sein/.cache/huggingface
# 공개 모델에는 HF_TOKEN이 필요하지 않다.
# HF_TOKEN=
```

`LAYA_REQUIRE_CUDA=true`이면 CUDA를 사용할 수 없거나 추론 중 CPU fallback이
발생할 때 오류로 처리한다. CPU 결과가 GPU 성능 측정에 섞이는 것을 방지하기
위한 설정이다.

### 10.6 모델 다운로드 없는 구조 테스트

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest tests.test_laya_selector -v
```

이 테스트는 가짜 CUDA agent를 주입하므로 Hugging Face 접속과 실제 GPU가
필요하지 않다. 모델 성능을 평가하는 테스트는 아니다.

### 10.7 실제 GPU smoke test

첫 실행에서는 checkpoint를 다운로드하므로 이후 실행보다 오래 걸린다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python - <<'PY'
from simulation.route_selector import get_selector

selector = get_selector()
try:
    result = selector.select_route(
        {"start_node": 2, "target_node": 10},
        {
            "route_a": "path=[2,5,4,6,13,8,9,10], distance=3.033652",
            "route_b": "path=[2,5,4,6,10], distance=1.592143",
        },
    )
    print("choice:", result["choice"])
    print("confidence:", result["confidence"])
    print("runtime:", result["runtime"])
    print("load_seconds:", result["load_duration_seconds"])
    print("eval_seconds:", result["eval_duration_seconds"])
finally:
    selector.release()
PY
```

정상 결과의 `runtime.device`는 `cuda:0`이어야 하며 precision은
`float16` 또는 `bfloat16`으로 표시되어야 한다. 다른 터미널에서는 다음
명령으로 메모리와 GPU 사용량을 확인한다.

```bash
sudo tegrastats
```

### 10.8 Laya 반복 벤치마크 실행

언어, 질문 난이도, 최단 경로, 정답 선택지 위치에 따른 정확도와 지연시간을
측정한다. 기본값은 케이스별 5회, 예열 1회, 실시간 기준 0.15초다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/laya-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 \
  --warmups 1 \
  --deadline 0.15
```

생성 파일:

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태와 요청/실제 장치, GPU 이름, precision, CPU fallback 횟수 |
| `selector_latency_trials.jsonl` | 개별 실행 입력·응답·정답 여부·시간 |
| `selector_latency_summary.json` | 전체 및 조건별 정확도·지연시간 집계 |
| `selector_latency_samples.csv` | 그래프와 통계 분석용 개별 측정값 |

choice, score, noul 질문 유형과 한국어·영어 결과를 별도로 측정하려면 다음을
실행한다.

```bash
python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/laya-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 \
  --warmups 1
```

생성 파일:

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태와 요청/실제 장치, GPU 이름, precision, CPU fallback 횟수 |
| `selector_question_type_trials.jsonl` | 질문 유형별 개별 실행 결과 |
| `selector_question_type_summary.json` | 언어·질문 유형별 정확도와 시간 |
| `selector_question_type_samples.csv` | 그래프와 통계 분석용 측정값 |

두 명령은 smoke test가 아니라 실제 Laya checkpoint를 사용한다. 첫 명령은
직관·사고·최단거리 질문을 한국어/영어로 구성하고 정답을 5개 위치에 한 번씩
옮겨 케이스당 5회 측정한다. 두 번째 명령은 choice·score·noul을 케이스당
5회 측정한다. RTX 4070 SUPER에서도 같은 환경변수와 명령을 사용하며, 실행
후 `manifest.json`의 `device.actual`, `device.kind`, `device.device_name`이 각각
`cuda:0`, `gpu`, `NVIDIA GeForce RTX 4070 SUPER`인지 확인한다.

### 10.9 오류 확인

CUDA 사용 여부:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

`False`이면 현재 가상환경의 PyTorch가 Jetson CUDA를 지원하지 않는 상태다.

CUDA 메모리와 시스템 메모리 확인:

```bash
free -h
sudo tegrastats
```

메모리가 부족하면 다른 모델 서버와 불필요한 프로세스를 종료하고
`LAYA_MAX_LENGTH=512`로 낮춰 smoke test부터 다시 실행한다. selector의
`release()`는 모델 참조와 CUDA cache를 해제한다.

Hugging Face cache와 저장공간 확인:

```bash
du -sh "$HF_HOME"
df -h ~
```

cache를 삭제하면 다음 실행 때 모델을 다시 다운로드한다.
