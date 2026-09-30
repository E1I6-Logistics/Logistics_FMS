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
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
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

Jetson에서는 모델 하나와 요청 하나만 처리하도록 서버를 실행한다. Ollama가
이미 systemd 서비스라면 같은 환경변수를 서비스 설정에 넣고 재시작한다.

```bash
OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 ollama serve
```

Jetson 시험은 별도 FP16·Q8 태그를 지정하지 않고 각 모델의 **Ollama 기본
태그**를 사용한다. 같은 명령으로 다시 설치할 수 있고, `ollama list`에 표시된
실제 크기와 양자화 방식도 결과와 함께 기록한다.

```bash
ollama pull qwen3:0.6b
ollama pull deepseek-r1:1.5b
ollama pull llama3.2:3b
ollama pull qwen3:4b
ollama pull gemma3:4b
```

다운로드 후 실제 태그, 파일 크기, 양자화 방식과 실행 장치를 확인한다.

```bash
ollama list
ollama show qwen3:0.6b
ollama ps
```

실제 실행 메모리는 모델 파일 크기와 같지 않다. KV cache, Ollama 버퍼와
운영체제 메모리가 추가되므로 최종 구동 여부는 `manifest.json`의
`device.models`, `ollama ps`, `tegrastats`로 판정한다. 저장공간이 부족하면
모델별 결과를 백업한 후 `ollama rm 모델태그`로 이전 모델을 제거한다.

다른 컴퓨터의 Ollama 서버를 사용하면 실행 전에 주소를 지정한다.

```bash
export OLLAMA_HOST=http://서버주소:11434
```

## 5. Jetson 또는 원격 컴퓨터에서 본 시험 실행

Jetson용 설정은 `simulation/evaluation/route_generation_benchmark_jetson.json`이다.
Ollama 기본 태그 5개를 `num_ctx=2048`, `num_predict=512`로 모델 하나씩
실행한다.
`num_ctx`는 입력과 출력을 포함하는 문맥 창이고 `num_predict`는 출력 생성
상한이므로 서로 같은 값이 아니다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --output simulation/benchmark_results/jetson-default-tags-$(date +%Y%m%d-%H%M%S)
```

실행기는 모델별 예열 1회를 집계에서 제외하고 5개 경로를 각 5회 실행한다.
총 본 시험은 `5개 모델 × 5개 경로 × 5회 = 125회`다. 터미널에는 모델,
경로, 반복 번호, 유효 경로 여부, 최단 거리 일치 여부, 응답 시간이 출력된다.

중단된 실행은 같은 폴더로 재개한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --resume simulation/benchmark_results/jetson-default-tags-실행시각
```

설치하지 않은 모델이 있으면 해당 요청은 실패한다. 모델 일부만 시험하려면
원본 설정을 즉석에서 바꾸지 말고 복사본에 새 `benchmark_id`와 모델 목록을
지정해 별도 실험으로 남긴다.

## 6. 생성되는 파일

| 파일 | 용도 |
| --- | --- |
| `manifest.json` | Git 상태, 장비, 모델별 `cpu/gpu/mixed`와 VRAM 적재량, Ollama 버전, 그래프·프롬프트·설정 해시 |
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
  --export-results simulation/benchmark_results/jetson-default-tags-실행시각
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

## 9. PC 10종과 Jetson 5종 평가 구분

### 9.1 PC용 대표 모델 10종

`simulation/evaluation/route_generation_benchmark_v3.json`은 RTX 4070 SUPER처럼
저장공간과 GPU 메모리가 충분한 PC의 기존 10종 시험을 재현한다.

| 모델 | 파라미터 | Ollama 기본 파일 | 기존 PC 시험 역할 |
| --- | ---: | ---: | --- |
| `qwen3:0.6b` | 0.6B | 523MB | 초경량 속도 기준 |
| `deepseek-r1:1.5b` | 1.5B | 1.1GB | thinking·출력 실패 비교군 |
| `llama3.2:3b` | 3B | 2.0GB | Meta 경량 비교군 |
| `qwen3:4b` | 4B | 2.5~2.6GB | 속도·정확도 균형 후보 |
| `gemma3:4b` | 4B | 3.3GB | Google 경량 비교군 |
| `llama3.1:8b` | 8B | 4.9GB | Meta 중형 비교군 |
| `mistral-nemo:12b` | 12B | 7.1GB | 정확도 우선 비교군 |
| `gemma3:12b` | 12B | 8.1GB | Gemma 크기 증가 비교군 |
| `deepseek-r1:14b` | 14B | 9.0GB | thinking 재평가 대상 |
| `phi4:14b` | 14B | 9.1GB | 유효 경로 우선 후보 |

이 설정의 모델 파일 합은 약 48GB이므로 Jetson에는 전부 다운로드하지 않는다.
PC에서 재현할 때만 다음을 사용한다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --check

python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_v3.json \
  --output simulation/benchmark_results/pc-v3-$(date +%Y%m%d-%H%M%S)
```

### 9.2 Jetson Ollama 기본 태그 5종

Jetson에서는 `simulation/evaluation/route_generation_benchmark_jetson.json`을
사용한다. `qwen3:0.6b`, `deepseek-r1:1.5b`, `llama3.2:3b`,
`qwen3:4b`, `gemma3:4b`의 Ollama 기본 태그를 사용하며, 경로는 PC 시험과
동일한 다섯 개다.

| 출발→도착 | 기준 최단 경로 | 거리 |
| --- | --- | ---: |
| 0→4 | 0 → 3 → 4 | 0.840354 |
| 0→6 | 0 → 3 → 4 → 6 | 1.234618 |
| 2→10 | 2 → 5 → 4 → 6 → 10 | 1.592143 |
| 1→12 | 1 → 4 → 6 → 13 → 12 | 1.899060 |
| 7→2 | 7 → 8 → 9 → 10 → 6 → 4 → 5 → 2 | 2.672242 |

구조 검증은 모델을 호출하지 않는다.

```bash
python -m simulation.evaluation.benchmark \
  --config simulation/evaluation/route_generation_benchmark_jetson.json \
  --check
```

메모리상 실행 가능하다는 사실만으로 모델을 채택하지 않는다. 기존 PC 시험에서
`llama3.2:3b`는 최단 경로 0/25였고 `deepseek-r1:1.5b`도 JSON 결과가
0/25였다. `qwen3:0.6b`는 10/25, `qwen3:4b`와 `gemma3:4b`는 15/25였다.
Jetson에서는 다음 순서로 최종 후보를 고른다.

1. `manifest.json`에서 실제 GPU 적재와 CPU fallback 여부를 확인한다.
2. 유효 경로와 최단 경로 정확도를 확인한다.
3. 정확도 조건을 통과한 모델끼리 중앙 응답시간을 비교한다.
4. 0.15초 실시간 기준 충족 여부는 별도 지표로 기록한다.

즉 “구동 가능”은 메모리 선별 결과이고 “최종 채택”은 정확도와 속도를 다시
측정한 뒤 결정한다.

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

## 11. Kev 경로 선택 시험

Kev는 경로를 생성하는 Ollama 모델이 아니라 `choice`, `score`, `noul` 질문에
확률을 반환하는 결정 모델이다. 이 저장소의 `KevSelector`는 Kev 서버가 제공하는
TypeSafe System One 호환 API인 `GET /v1/models`와 `POST /v1/systemone`을
호출한다. Kev의 pointer head와 temperature calibration을 포함한 공식 runtime을
사용하므로 일반 PEFT 모델처럼 adapter만 직접 불러오지 않는다.

### 11.1 서버 없는 인터페이스 테스트

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate
python -m unittest tests.test_kev_selector -v
```

이 테스트는 가짜 HTTP 응답으로 API 요청, choice·score·noul 파싱, 전체 확률,
confidence와 CUDA 강제 검사를 확인한다. 실제 Kev 모델의 정확도와 속도를
측정하는 시험은 아니다.

### 11.2 실제 Kev 서버 준비

Kev 공식 저장소를 별도 디렉터리에 설치하고 가장 작은 공개 checkpoint인
`jaredpalmer/kev-0.8b`부터 실행한다. `uv`가 없다면 먼저 공식 설치 방법으로
설치한다.

```bash
git clone https://github.com/jaredpalmer/kev.git ~/kev
cd ~/kev
uv sync --extra serve
uv run --extra serve python -m kev.serve \
  --run jaredpalmer/kev-0.8b \
  --port 8009
```

서버 터미널은 계속 실행해 둔다. 다른 터미널에서 메타데이터와 장치를 확인한다.

```bash
curl http://127.0.0.1:8009/v1/models
```

Jetson 실제 GPU 시험에서는 응답의 `device`가 `cuda` 또는 `cuda:0`인지 먼저
확인한다. Kev 0.8B의 공식 실행 가능 장비 표에는 L4와 Apple Silicon이 명시되어
있으며 Jetson은 명시되어 있지 않으므로, Jetson 실행 가능 여부는 이 단계에서
직접 검증해야 한다.

### 11.3 FMS 선택기 설정

`simulation/.env`에 다음 값을 설정한다.

```dotenv
ROUTE_SELECTOR=kev
KEV_HOST=http://127.0.0.1:8009
KEV_MODEL=kev-latest
KEV_TIMEOUT_SECONDS=60
KEV_REQUIRE_CUDA=true
# 로컬 기본 서버에 인증을 설정하지 않았다면 비워 둔다.
# KEV_API_KEY=
```

### 11.4 실제 Kev 반복 시험

Laya와 동일한 케이스와 결과 형식으로 실행한다.

```bash
cd ~/Logistics_FMS
source ~/venv/robot/bin/activate

python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/kev-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 \
  --warmups 1 \
  --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/kev-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 \
  --warmups 1
```

결과에는 선택기 이름, 요청 모델, 응답 모델, confidence, 전체 probabilities,
정답 여부와 wall/model 지연시간이 저장된다. `manifest.json`의 `device`에서
실제 Kev 서버가 보고한 backend, dtype과 장치를 함께 확인한다.

## 12. PC와 Jetson 선택 모델 비교

Laya와 Kev는 Ollama 모델의 경로 직접 생성 시험과 분리하여 비교한다. 두 장비에서
동일한 Git 커밋, checkpoint, 케이스, 반복 횟수와 입력 제한을 사용하고 출력
폴더만 장비별로 구분한다.

### 12.1 고정 조건

| 항목 | Laya | Kev |
| --- | --- | --- |
| checkpoint | `convaiinnovations/laya-multilingual` | `jaredpalmer/kev-0.8b` |
| 역할 | 경로 후보 선택 | 경로 후보 선택 |
| 시험 | latency 및 choice·score·noul | latency 및 choice·score·noul |
| 반복 | 케이스별 5회 | 케이스별 5회 |
| 예열 | 케이스 그룹별 1회 | 케이스 그룹별 1회 |
| 실시간 기준 | 0.15초 | 0.15초 |

checkpoint나 입력 길이를 바꾸면 장비 차이와 모델 차이가 섞이므로 같은 비교에
포함하지 않는다. 변경 시험은 별도 출력 폴더와 별도 결과로 보관한다.

### 12.2 Laya 실행

PC와 Jetson 모두 `simulation/.env`에서 다음 값은 동일하게 사용한다.

```dotenv
ROUTE_SELECTOR=laya
LAYA_HF_MODEL=convaiinnovations/laya-multilingual
LAYA_DEVICE=cuda:0
LAYA_REQUIRE_CUDA=true
LAYA_MAX_LENGTH=1024
```

PC에서는 다음처럼 실행한다.

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/pc-rtx4070-laya-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/pc-rtx4070-laya-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1
```

Jetson에서도 같은 명령과 인자를 사용하고 출력 이름만 구분한다.

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/jetson-orin-laya-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/jetson-orin-laya-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1
```

### 12.3 Kev 실행

양쪽 장비에서 같은 `jaredpalmer/kev-0.8b` 서버를 로컬로 실행하고
`simulation/.env`에는 다음 값을 사용한다.

```dotenv
ROUTE_SELECTOR=kev
KEV_HOST=http://127.0.0.1:8009
KEV_MODEL=kev-latest
KEV_TIMEOUT_SECONDS=60
KEV_REQUIRE_CUDA=true
```

PC 결과:

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/pc-rtx4070-kev-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/pc-rtx4070-kev-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1
```

Jetson 결과:

```bash
python -m simulation.evaluation.selector_latency_benchmark \
  --output simulation/benchmark_results/jetson-orin-kev-latency-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1 --deadline 0.15

python -m simulation.evaluation.selector_question_types_benchmark \
  --output simulation/benchmark_results/jetson-orin-kev-question-types-$(date +%Y%m%d-%H%M%S) \
  --repeats 5 --warmups 1
```

### 12.4 비교 지표

장비별 `manifest.json`, summary JSON과 CSV에서 다음 값을 비교한다.

- `selector_name`, `requested_model`, `response_model`
- `device.actual`, `device.device_name`, `device.precision`
- CPU fallback 횟수와 오류 횟수
- 전체 정확도와 한국어·영어 정확도
- 직관·사고·최단거리 질문별 정확도
- choice·score·noul 질문별 정확도
- wall latency와 model latency의 평균·중앙값·p95
- 0.15초 실시간 기준 충족률
- confidence 및 전체 선택지 probabilities

PC와 Jetson의 정확도는 원칙적으로 같아야 한다. 차이가 발생하면 precision,
checkpoint revision, 라이브러리 버전과 입력 잘림 여부를 먼저 확인한다. 속도는
중앙값과 p95를 함께 사용하고, 첫 모델 로드 시간은 예열 결과로 분리한다.
